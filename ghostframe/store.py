"""Short SQLite transactions; no application update/delete path for evidence."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

from pydantic import ValidationError

from .models import Event, GFError, canonical, digest
from .policies import CapturePolicy, Limits, RetentionPolicy
from .processes import alive

ANCHOR = "0" * 64


class Store:
    _guards: ClassVar[dict[str, tuple[threading.RLock, dict]]] = {}
    _guard_lock = threading.Lock()

    def __init__(
        self,
        path: str | Path,
        *,
        policy: CapturePolicy | None = None,
        limits: Limits | None = None,
        retention: RetentionPolicy | None = None,
        clock=None,
    ):
        for value, expected in ((policy, CapturePolicy), (limits, Limits), (retention, RetentionPolicy)):
            if value is not None and not isinstance(value, expected):
                raise TypeError("Configuration requires a structured policy object")
        self.path = Path(path)
        self.policy = policy or CapturePolicy()
        self.limits = limits or Limits()
        self.retention = retention or RetentionPolicy()
        self.clock = clock or time.time
        self._policies: dict[str, CapturePolicy] = {}
        with self._guard_lock:
            self._lock, self._active = self._guards.setdefault(
                str(self.path.resolve()), (threading.RLock(), {})
            )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, metadata TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events(run_id TEXT REFERENCES runs(id), seq INTEGER,
              id TEXT UNIQUE, body TEXT NOT NULL, PRIMARY KEY(run_id,seq));
            CREATE TABLE IF NOT EXISTS checkpoints(id TEXT PRIMARY KEY,run_id TEXT REFERENCES runs(id),
              body TEXT NOT NULL,digest TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS checkpoints_run ON checkpoints(run_id);
            CREATE TABLE IF NOT EXISTS lifecycle(run_id TEXT PRIMARY KEY REFERENCES runs(id),
                policy TEXT NOT NULL, completed REAL, expires REAL, pinned INTEGER NOT NULL DEFAULT 0,
                retained_bytes INTEGER NOT NULL DEFAULT 0, parent_id TEXT REFERENCES runs(id));
            CREATE TABLE IF NOT EXISTS cleanup_log(id TEXT PRIMARY KEY, at REAL, removed TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS operations(token TEXT PRIMARY KEY,pid INTEGER NOT NULL,run_id TEXT);
            CREATE TABLE IF NOT EXISTS storage_usage(id INTEGER PRIMARY KEY CHECK(id=1),bytes INTEGER NOT NULL);
            CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
              BEGIN SELECT RAISE(ABORT,'append-only events'); END;
            CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
              BEGIN SELECT RAISE(ABORT,'append-only events'); END;
            CREATE TRIGGER IF NOT EXISTS checkpoints_no_update BEFORE UPDATE ON checkpoints
              BEGIN SELECT RAISE(ABORT,'immutable checkpoint'); END;
            CREATE TRIGGER IF NOT EXISTS checkpoints_no_delete BEFORE DELETE ON checkpoints
              BEGIN SELECT RAISE(ABORT,'immutable checkpoint'); END;
            CREATE TRIGGER IF NOT EXISTS runs_no_update BEFORE UPDATE ON runs
              BEGIN SELECT RAISE(ABORT,'immutable run metadata'); END;
            CREATE TRIGGER IF NOT EXISTS runs_no_delete BEFORE DELETE ON runs
              BEGIN SELECT RAISE(ABORT,'immutable run metadata'); END;
            """)
            if not db.execute("SELECT 1 FROM storage_usage WHERE id=1").fetchone():
                total = 0
                for table, column in (
                    ("runs", "metadata"),
                    ("events", "body"),
                    ("checkpoints", "body"),
                    ("cleanup_log", "removed"),
                ):
                    total += db.execute(
                        f"SELECT COALESCE(SUM(length(CAST({column} AS BLOB))),0) FROM {table}"
                    ).fetchone()[0]
                db.execute("INSERT OR IGNORE INTO storage_usage VALUES (1,?)", (total,))
        if self.retention.enabled and self.retention.cleanup_on_startup:
            self.cleanup(apply=True)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, metadata: dict, *, policy: CapturePolicy | None = None) -> str:
        policy = policy or self.policy
        self.limits.check(metadata, self.limits.checkpoint_bytes)
        rid = uuid.uuid4().hex
        safe, _ = policy.capture(metadata, "__metadata__", limits=self.limits)
        controls = {
            k: metadata[k]
            for k in (
                "driver_version",
                "provenance",
                "parent_id",
                "source_event",
                "source_checkpoint",
                "fork_step",
                "shared_prefix_end",
            )
            if k in metadata
        }
        # Internal IDs/counters cannot become an unrestricted payload bypass.
        for key in ("parent_id", "source_event", "source_checkpoint"):
            if key in controls and (
                not isinstance(controls[key], str)
                or len(controls[key]) != 32
                or any(c not in "0123456789abcdef" for c in controls[key])
            ):
                raise GFError("INVALID_METADATA", "Invalid ancestry identifier")
        for key in ("fork_step", "shared_prefix_end"):
            if key in controls and (not isinstance(controls[key], int) or controls[key] < 0):
                raise GFError("INVALID_METADATA", "Invalid ancestry counter")
        if controls.get("driver_version") not in {None, "document-agent.v1"}:
            controls["driver_version"] = None
        if controls.get("provenance") not in {
            "RECORDED",
            "REPLAYED_DETERMINISTICALLY",
            "REEXECUTED_SCRIPTED",
        }:
            controls["provenance"] = "RECORDED"
        data = {
            **(safe if isinstance(safe, dict) else {}),
            **controls,
            "name": safe.get("name", "Metadata-only run") if isinstance(safe, dict) else "Metadata-only run",
            "id": rid,
            "created": datetime.fromtimestamp(self.clock(), UTC).isoformat(),
            "capture_policy": policy.descriptor(),
        }
        n = len(canonical(data).encode("utf-8"))
        if n > self.limits.run_bytes:
            raise GFError("STORAGE_QUOTA_EXCEEDED", "Run metadata exceeds storage budget")
        with self._lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT count(*) FROM runs").fetchone()[0] >= self.limits.runs:
                raise GFError("RUN_LIMIT_EXCEEDED", "Retained run count exceeded")
            self._store_budget(db, n)
            parent = controls.get("parent_id")
            if parent and not db.execute("SELECT 1 FROM runs WHERE id=?", (parent,)).fetchone():
                raise GFError("RUN_NOT_FOUND", "Parent run does not exist")
            for key, table in (("source_event", "events"), ("source_checkpoint", "checkpoints")):
                if controls.get(key):
                    owner = db.execute(f"SELECT run_id FROM {table} WHERE id=?", (controls[key],)).fetchone()
                    if not owner or owner[0] != parent:
                        raise GFError("INVALID_METADATA", "Ancestry reference does not belong to the parent")
            ancestor = parent
            depth = 0
            seen = set()
            while ancestor:
                depth += 1
                if ancestor in seen or depth > self.limits.branch_depth:
                    raise GFError("BRANCH_DEPTH_LIMIT_EXCEEDED", "Ancestry depth exceeds configured budget")
                seen.add(ancestor)
                ancestor = db.execute(
                    "SELECT json_extract(metadata,'$.parent_id') FROM runs WHERE id=?", (ancestor,)
                ).fetchone()[0]
            if controls.get("provenance") == "REEXECUTED_SCRIPTED":
                count = db.execute(
                    "SELECT count(*) FROM lifecycle l JOIN runs r ON r.id=l.run_id WHERE l.parent_id=? "
                    "AND json_extract(r.metadata,'$.provenance')='REEXECUTED_SCRIPTED'",
                    (parent,),
                ).fetchone()[0]
                if count >= self.limits.branches:
                    raise GFError("BRANCH_LIMIT_EXCEEDED", "Retained child limit exceeded")
            db.execute("INSERT INTO runs VALUES (?,?)", (rid, canonical(data)))
            db.execute(
                "INSERT INTO lifecycle(run_id,policy,retained_bytes,parent_id) VALUES (?,?,?,?)",
                (
                    rid,
                    canonical(
                        {
                            **policy.descriptor(),
                            "retention": {
                                "enabled": self.retention.enabled,
                                "days": self.retention.retention_days,
                            },
                        }
                    ),
                    n,
                    parent,
                ),
            )
            db.execute("UPDATE storage_usage SET bytes=bytes+? WHERE id=1", (n,))
        self._policies[rid] = policy
        return rid

    def metadata(self, rid: str) -> dict:
        with self.connect() as db:
            n = db.execute("SELECT length(CAST(metadata AS BLOB)) FROM runs WHERE id=?", (rid,)).fetchone()
            if n and n[0] > self.limits.checkpoint_bytes:
                raise GFError("PAYLOAD_TOO_LARGE", "Stored metadata exceeds read budget")
            row = db.execute("SELECT metadata FROM runs WHERE id=?", (rid,)).fetchone()
        if not row:
            raise GFError("RUN_NOT_FOUND", "Run does not exist")
        return json.loads(row[0])

    def events(self, rid: str) -> list[dict]:
        self.metadata(rid)
        with self.connect() as db:
            n, count = db.execute(
                "SELECT COALESCE(SUM(length(CAST(body AS BLOB))),0),count(*) FROM events WHERE run_id=?",
                (rid,),
            ).fetchone()
            if n > self.limits.run_bytes + 4096 or count > self.limits.events + 1:
                raise GFError("RESPONSE_LIMIT_EXCEEDED", "Stored events exceed read budget")
            rows = db.execute("SELECT body FROM events WHERE run_id=? ORDER BY seq", (rid,)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def append(self, rid: str, kind: str, payload: Any = None, **fields) -> dict:
        if set(fields) - {
            "parent",
            "capture_complete",
            "actor",
            "tool",
            "step",
            "status",
            "provenance",
            "checkpoint",
        }:
            raise GFError("INVALID_EVENT", "Unsupported event metadata field")
        policy = self._policies.get(rid, CapturePolicy())
        self.limits.check(payload)
        payload, complete = policy.capture(payload, fields.get("tool"), limits=self.limits)
        fields["capture_complete"] = complete and fields.get("capture_complete", True)
        self.limits.check(fields)
        if policy.mode != "synthetic_fixture" and policy.effective_mode != "legacy_explicit":
            fields["actor"] = "agent"
            if fields.get("tool") is not None and fields["tool"] not in policy.allowed_tools:
                fields["tool"] = "unlisted_tool"
            if fields.get("status") not in {None, "OK", "ERROR"}:
                fields["status"] = "ERROR"
            if fields.get("provenance") not in {
                None,
                "RECORDED",
                "DIVERGED",
                "REEXECUTED_SCRIPTED",
                "REPLAYED_DETERMINISTICALLY",
            }:
                fields["provenance"] = "RECORDED"
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if fields.get("checkpoint"):
                owner = db.execute(
                    "SELECT run_id FROM checkpoints WHERE id=?", (fields["checkpoint"],)
                ).fetchone()
                if not owner or owner[0] != rid:
                    raise GFError("CHECKPOINT_MISSING", "Checkpoint must belong to the current run")
            row = db.execute(
                "SELECT seq,body FROM events WHERE run_id=? ORDER BY seq DESC LIMIT 1", (rid,)
            ).fetchone()
            if row and json.loads(row[1])["kind"] in {"RUN_COMPLETED", "RUN_FAILED"}:
                raise GFError("RUN_FINALIZED", "Cannot append after run finalization")
            seq, previous = (row[0] + 1, json.loads(row[1])["event_digest"]) if row else (0, ANCHOR)
            if seq >= self.limits.events:
                raise GFError("RUN_EVENT_LIMIT_EXCEEDED", "Run event budget exceeded")
            if fields.get("parent"):
                parent = db.execute(
                    "SELECT run_id,body FROM events WHERE id=?", (fields["parent"],)
                ).fetchone()
                if not parent or parent[0] != rid:
                    raise GFError("INVALID_PARENT", "Parent must be an earlier event in this run")
                if kind in {"TOOL_CALL_COMPLETED", "TOOL_CALL_FAILED"}:
                    p = json.loads(parent[1])
                    if p["kind"] != "TOOL_CALL_REQUESTED" or p["tool"] != fields.get("tool"):
                        raise GFError("INVALID_PARENT", "Completion must refer to its tool request")
                    if db.execute(
                        "SELECT 1 FROM events WHERE run_id=? AND json_extract(body,'$.parent')=? "
                        "AND json_extract(body,'$.kind') IN ('TOOL_CALL_COMPLETED','TOOL_CALL_FAILED')",
                        (rid, fields["parent"]),
                    ).fetchone():
                        raise GFError("DOUBLE_COMPLETION", "Tool request already completed")
            elif kind in {"TOOL_CALL_COMPLETED", "TOOL_CALL_FAILED"}:
                raise GFError("INVALID_PARENT", "Tool completion requires a request")
            try:
                event = Event(
                    event_id=uuid.uuid4().hex,
                    run_id=rid,
                    seq=seq,
                    kind=kind,  # type: ignore[arg-type]
                    payload=payload,
                    payload_hash=digest(payload, "ghostframe.payload.v1"),
                    timestamp=datetime.now(UTC).isoformat(),
                    monotonic_ns=time.monotonic_ns(),
                    previous_digest=previous,
                    event_digest="",
                    **fields,
                )
            except ValidationError:
                raise GFError("INVALID_EVENT", "Event metadata does not match the supported schema") from None
            body = event.model_dump()
            body["event_digest"] = digest(
                {k: v for k, v in body.items() if k != "event_digest"}, "ghostframe.event.v1"
            )
            self._charge(db, rid, len(canonical(body).encode("utf-8")))
            db.execute("INSERT INTO events VALUES (?,?,?,?)", (rid, seq, body["event_id"], canonical(body)))
            if kind in {"RUN_COMPLETED", "RUN_FAILED"}:
                completed = self.clock()
                expires = self._expiry_time(db, rid, completed)
                db.execute(
                    "UPDATE lifecycle SET completed=?,expires=? WHERE run_id=?", (completed, expires, rid)
                )
        return body

    def checkpoint(self, rid: str, state: dict) -> str:
        self.limits.check(state, self.limits.checkpoint_bytes, "CHECKPOINT_TOO_LARGE")
        state, _ = self._policies.get(rid, CapturePolicy()).capture(
            state, "__checkpoint__", limits=self.limits
        )
        cid = uuid.uuid4().hex
        body = {"schema_version": 1, "run_id": rid, "state": state}
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            last = db.execute(
                "SELECT json_extract(body,'$.kind') FROM events WHERE run_id=? ORDER BY seq DESC LIMIT 1",
                (rid,),
            ).fetchone()
            if last and last[0] in {"RUN_COMPLETED", "RUN_FAILED"}:
                raise GFError("RUN_FINALIZED", "Cannot checkpoint after finalization")
            if (
                db.execute("SELECT count(*) FROM checkpoints WHERE run_id=?", (rid,)).fetchone()[0]
                >= self.limits.checkpoints
            ):
                raise GFError("CHECKPOINT_LIMIT_EXCEEDED", "Checkpoint count exceeded")
            self._charge(db, rid, len(canonical(body).encode("utf-8")))
            db.execute("INSERT INTO checkpoints VALUES (?,?,?,?)", (cid, rid, canonical(body), digest(body)))
        return cid

    def restore(self, cid: str, rid: str | None = None) -> dict:
        with self.connect() as db:
            size = db.execute(
                "SELECT length(CAST(body AS BLOB)) FROM checkpoints WHERE id=?", (cid,)
            ).fetchone()
            if size and size[0] > self.limits.checkpoint_bytes + 1024:
                raise GFError("CHECKPOINT_TOO_LARGE", "Stored checkpoint exceeds read budget")
            row = db.execute("SELECT run_id,body,digest FROM checkpoints WHERE id=?", (cid,)).fetchone()
        if not row:
            raise GFError("CHECKPOINT_MISSING", "Checkpoint does not exist")
        body = json.loads(row[1])
        if digest(body) != row[2] or body.get("schema_version") != 1 or (rid and row[0] != rid):
            raise GFError("CHECKPOINT_CORRUPT", "Checkpoint integrity, ownership or version mismatch")
        return body["state"]

    def checkpoints(self, rid: str) -> list[dict]:
        self.metadata(rid)
        with self.connect() as db:
            size, count = db.execute(
                "SELECT COALESCE(SUM(length(CAST(body AS BLOB))),0),count(*) FROM checkpoints WHERE run_id=?",
                (rid,),
            ).fetchone()
            if size > self.limits.run_bytes or count > self.limits.checkpoints:
                raise GFError("RESPONSE_LIMIT_EXCEEDED", "Stored checkpoints exceed read budget")
            rows = db.execute("SELECT id,body,digest FROM checkpoints WHERE run_id=?", (rid,)).fetchall()
        return [{"id": r[0], "body": json.loads(r[1]), "digest": r[2]} for r in rows]

    def verify(self, rid: str) -> dict:
        try:
            events = self.events(rid)
            previous = ANCHOR
            seen: dict[str, dict] = {}
            completed: set[str] = set()
            if not events or events[0]["kind"] != "RUN_STARTED":
                raise GFError("INTEGRITY_VIOLATION", "Missing run start")
            for seq, raw in enumerate(events):
                e = Event.model_validate(raw).model_dump()
                expected = digest({k: v for k, v in e.items() if k != "event_digest"}, "ghostframe.event.v1")
                if (
                    e["run_id"] != rid
                    or e["seq"] != seq
                    or e["previous_digest"] != previous
                    or e["event_digest"] != expected
                    or e["payload_hash"] != digest(e["payload"], "ghostframe.payload.v1")
                ):
                    raise GFError("INTEGRITY_VIOLATION", "Event chain or payload mismatch", {"seq": seq})
                if e["parent"] and e["parent"] not in seen:
                    raise GFError("INTEGRITY_VIOLATION", "Missing or forward parent", {"seq": seq})
                if e["kind"] in {"TOOL_CALL_COMPLETED", "TOOL_CALL_FAILED"}:
                    p = seen.get(e["parent"], {})
                    if (
                        p.get("kind") != "TOOL_CALL_REQUESTED"
                        or p.get("tool") != e["tool"]
                        or e["parent"] in completed
                    ):
                        raise GFError("INTEGRITY_VIOLATION", "Invalid completion", {"seq": seq})
                    completed.add(e["parent"])
                if e["checkpoint"]:
                    self.restore(e["checkpoint"], rid)
                seen[e["event_id"]] = e
                previous = e["event_digest"]
            for cp in self.checkpoints(rid):
                self.restore(cp["id"], rid)
            terminal = events[-1]["kind"] in {"RUN_COMPLETED", "RUN_FAILED"}
            requests = {e["event_id"] for e in events if e["kind"] == "TOOL_CALL_REQUESTED"}
            return {
                "valid": True,
                "complete": terminal and requests == completed,
                "events": len(events),
                "head": previous,
                "status": "VERIFIED" if terminal and requests == completed else "INCOMPLETE_CAPTURE",
            }
        except GFError:
            raise
        except (ValueError, KeyError, TypeError):
            raise GFError(
                "INTEGRITY_VIOLATION", "Stored evidence does not match the supported schema"
            ) from None

    def summary(self, rid: str) -> dict:
        meta, events = self.metadata(rid), self.events(rid)
        last = events[-1] if events else None
        try:
            integrity = self.verify(rid)
        except GFError as exc:
            integrity = {"valid": False, "status": exc.code}
        return {
            **meta,
            "event_count": len(events),
            "status": last["kind"] if last else "EMPTY",
            "outcome": last["payload"] if last and last["kind"] == "RUN_COMPLETED" else None,
            "integrity": integrity,
            "replay_eligible": meta.get("driver_version") == "document-agent.v1"
            and isinstance(meta.get("fixture"), dict)
            and all(k in meta["fixture"] for k in ("files", "ticket", "name", "goal_files"))
            and meta.get("provenance") != "REEXECUTED_SCRIPTED"
            and bool(integrity.get("complete"))
            and all(e["capture_complete"] for e in events),
        }

    def runs(self, limit: int = 100, offset: int = 0) -> list[dict]:
        if not 1 <= limit <= 200 or offset < 0:
            raise GFError("INVALID_PAGINATION", "Pagination outside configured bounds")
        with self.connect() as db:
            ids = db.execute(
                "SELECT id FROM runs ORDER BY rowid DESC LIMIT ? OFFSET ?", (limit, offset)
            ).fetchall()
        results = []
        size = 0
        for row in ids:
            summary = self.summary(row[0])
            size += len(canonical(summary).encode("utf-8"))
            if size > self.limits.response_bytes:
                raise GFError("RESPONSE_LIMIT_EXCEEDED", "Request a smaller run page")
            results.append(summary)
        return results

    def export(self, rid: str, _seen: set | None = None, _budget: list | None = None) -> dict:
        seen = set() if _seen is None else _seen
        budget = [self.limits.export_bytes] if _budget is None else _budget
        if rid in seen or len(seen) > self.limits.branch_depth + 1:
            raise GFError("EXPORT_LIMIT_EXCEEDED", "Export ancestry exceeds configured budget")
        seen.add(rid)
        with self.connect() as db:
            n = db.execute(
                "SELECT COALESCE(SUM(length(CAST(body AS BLOB))),0) FROM events WHERE run_id=?", (rid,)
            ).fetchone()[0]
            n += db.execute(
                "SELECT COALESCE(SUM(length(CAST(body AS BLOB))),0) FROM checkpoints WHERE run_id=?", (rid,)
            ).fetchone()[0]
            row = db.execute("SELECT length(CAST(metadata AS BLOB)) FROM runs WHERE id=?", (rid,)).fetchone()
            n += row[0] if row else 0
        budget[0] -= n
        if budget[0] < 0:
            raise GFError("EXPORT_LIMIT_EXCEEDED", "Export exceeds configured byte budget")
        verification = self.verify(rid)
        bundle: dict[str, Any] = {
            "schema_version": 1,
            "metadata": self.metadata(rid),
            "events": self.events(rid),
            "checkpoints": self.checkpoints(rid),
            "verification": verification,
        }
        parent = bundle["metadata"].get("parent_id")
        if parent:
            bundle["parent_evidence"] = self.export(parent, seen, budget)
        result = {"bundle": bundle, "digest": digest(bundle, "ghostframe.bundle.v1")}
        if len(canonical(result).encode("utf-8")) > self.limits.export_bytes:
            raise GFError("EXPORT_LIMIT_EXCEEDED", "Export exceeds configured byte budget")
        return result

    def _charge(self, db, rid: str, n: int):
        row = db.execute("SELECT retained_bytes FROM lifecycle WHERE run_id=?", (rid,)).fetchone()
        if not row:
            raise GFError(
                "LEGACY_WRITE_DENIED", "Legacy histories must be explicitly migrated before new writes"
            )
        if row[0] + n > self.limits.run_bytes:
            raise GFError("STORAGE_QUOTA_EXCEEDED", "Run storage budget exceeded")
        self._store_budget(db, n)
        db.execute("UPDATE lifecycle SET retained_bytes=retained_bytes+? WHERE run_id=?", (n, rid))
        db.execute("UPDATE storage_usage SET bytes=bytes+? WHERE id=1", (n,))

    def _store_budget(self, db, n: int):
        total = db.execute("SELECT bytes FROM storage_usage WHERE id=1").fetchone()[0]
        if total + n > self.limits.store_bytes:
            raise GFError("STORAGE_QUOTA_EXCEEDED", "Store logical byte budget exceeded")

    def fail(self, rid: str, code: str):
        """One bounded reserved terminal record; cannot be used to persist caller payloads."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT seq,body FROM events WHERE run_id=? ORDER BY seq DESC LIMIT 1", (rid,)
            ).fetchone()
            if not row or json.loads(row[1])["kind"] in {"RUN_COMPLETED", "RUN_FAILED"}:
                return
            previous = json.loads(row[1])
            payload = {
                "code": code
                if code
                in {
                    "RUN_EVENT_LIMIT_EXCEEDED",
                    "STORAGE_QUOTA_EXCEEDED",
                    "PAYLOAD_TOO_LARGE",
                    "CHECKPOINT_TOO_LARGE",
                    "CHECKPOINT_LIMIT_EXCEEDED",
                    "FILESYSTEM_QUOTA_EXCEEDED",
                    "EXECUTION_TIMEOUT",
                    "REPLAY_STEP_LIMIT_EXCEEDED",
                    "BRANCH_TIMEOUT",
                    "EXECUTION_CANCELLED",
                    "EVENT_MISMATCH",
                    "STATE_MISMATCH",
                }
                else "EXECUTION_FAILED"
            }
            body = Event(
                event_id=uuid.uuid4().hex,
                run_id=rid,
                seq=row[0] + 1,
                kind="RUN_FAILED",
                payload=payload,
                payload_hash=digest(payload, "ghostframe.payload.v1"),
                timestamp=datetime.now(UTC).isoformat(),
                monotonic_ns=time.monotonic_ns(),
                previous_digest=previous["event_digest"],
                event_digest="",
                status="ERROR",
                capture_complete=False,
                provenance="DIVERGED",
            ).model_dump()
            body["event_digest"] = digest(
                {k: v for k, v in body.items() if k != "event_digest"}, "ghostframe.event.v1"
            )
            db.execute(
                "INSERT INTO events VALUES (?,?,?,?)", (rid, body["seq"], body["event_id"], canonical(body))
            )
            n = len(canonical(body).encode("utf-8"))
            db.execute("UPDATE lifecycle SET retained_bytes=retained_bytes+? WHERE run_id=?", (n, rid))
            db.execute("UPDATE storage_usage SET bytes=bytes+? WHERE id=1", (n,))
            at = self.clock()
            db.execute(
                "UPDATE lifecycle SET completed=?,expires=? WHERE run_id=?",
                (at, self._expiry_time(db, rid, at), rid),
            )

    def _expiry_time(self, db, rid: str, at: float):
        row = db.execute("SELECT policy FROM lifecycle WHERE run_id=?", (rid,)).fetchone()
        retention = json.loads(row[0]).get("retention", {}) if row else {}
        return at + retention["days"] * 86400 if retention.get("enabled") else None

    @contextmanager
    def operation(self, rid: str | None = None):
        token = uuid.uuid4().hex
        with self._lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._prune_operations(db)
            if db.execute("SELECT count(*) FROM operations").fetchone()[0] >= self.limits.active_operations:
                raise GFError("CONCURRENCY_LIMIT_EXCEEDED", "Active operation budget exceeded")
            if rid:
                self.metadata(rid)
            db.execute("INSERT INTO operations VALUES (?,?,?)", (token, os.getpid(), rid))
            self._active[token] = rid
        try:
            yield
        finally:
            with self._lock:
                self._active.pop(token, None)
                with self.connect() as db:
                    db.execute("DELETE FROM operations WHERE token=?", (token,))

    def _prune_operations(self, db):
        for token, pid in db.execute("SELECT token,pid FROM operations").fetchall():
            if not alive(pid):
                db.execute("DELETE FROM operations WHERE token=?", (token,))

    def event_page(self, rid: str, limit: int, offset: int) -> dict:
        if not 1 <= limit <= 500 or offset < 0:
            raise GFError("INVALID_PAGINATION", "Pagination outside configured bounds")
        self.metadata(rid)
        with self.connect() as db:
            total = db.execute("SELECT count(*) FROM events WHERE run_id=?", (rid,)).fetchone()[0]
            size = db.execute(
                "SELECT COALESCE(SUM(n),0) FROM (SELECT length(CAST(body AS BLOB)) AS n FROM events "
                "WHERE run_id=? ORDER BY seq LIMIT ? OFFSET ?)",
                (rid, limit, offset),
            ).fetchone()[0]
            if size > self.limits.response_bytes:
                raise GFError("RESPONSE_LIMIT_EXCEEDED", "Request a smaller event page")
            rows = db.execute(
                "SELECT body FROM events WHERE run_id=? ORDER BY seq LIMIT ? OFFSET ?", (rid, limit, offset)
            ).fetchall()
        if sum(len(r[0].encode("utf-8")) for r in rows) > self.limits.response_bytes:
            raise GFError("RESPONSE_LIMIT_EXCEEDED", "Request a smaller event page")
        return {"events": [json.loads(r[0]) for r in rows], "total": total, "offset": offset}

    def pin(self, rid: str, value: bool = True):
        with self.connect() as db:
            if db.execute("UPDATE lifecycle SET pinned=? WHERE run_id=?", (int(value), rid)).rowcount != 1:
                raise GFError("RUN_NOT_FOUND", "Managed run does not exist")

    def _expiry(self, db) -> tuple[list[str], dict]:
        rows = db.execute(
            "SELECT r.id,l.expires,l.completed,l.pinned,json_extract(r.metadata,'$.parent_id') "
            "FROM runs r LEFT JOIN lifecycle l ON r.id=l.run_id"
        ).fetchall()
        candidates = {
            r[0] for r in rows if r[1] is not None and r[1] <= self.clock() and r[2] is not None and not r[3]
        }
        self._prune_operations(db)
        protected = {r[0] for r in rows if r[0] not in candidates} | {
            r[0] for r in db.execute("SELECT run_id FROM operations WHERE run_id IS NOT NULL").fetchall()
        }
        parents = {r[0]: r[4] for r in rows}
        todo = list(protected)
        while todo:
            parent = parents.get(todo.pop())
            if parent and parent not in protected:
                protected.add(parent)
                todo.append(parent)
        return sorted(candidates - protected), parents

    def cleanup(self, *, apply: bool = False, interrupt=None) -> dict:
        with self._lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            ids, parents = self._expiry(db) if self.retention.enabled else ([], {})
            result = {
                "enabled": self.retention.enabled,
                "database": str(self.path.resolve()),
                "expired_runs": ids,
                "artifacts": [
                    f"SQLite:{table}:run={rid}"
                    for rid in ids
                    for table in ("events", "checkpoints", "runs", "lifecycle")
                ],
                "applied": apply,
            }
            if apply and ids:
                # DDL and deletion share one transaction: readers never see triggers missing.
                triggers = db.execute(
                    "SELECT name,sql FROM sqlite_master WHERE type='trigger' AND name IN "
                    "('events_no_delete','checkpoints_no_delete','runs_no_delete')"
                ).fetchall()
                if len(triggers) != 3:
                    raise GFError("INTEGRITY_VIOLATION", "Expected immutability triggers missing")
                for name, _ in triggers:
                    db.execute(f"DROP TRIGGER {name}")
                if interrupt:
                    interrupt("triggers")
                pending = set(ids)
                while pending:
                    leaves = [
                        rid for rid in pending if not any(parents.get(child) == rid for child in pending)
                    ]
                    if not leaves:
                        raise GFError("INTEGRITY_VIOLATION", "Cyclic ancestry")
                    for rid in leaves:
                        charge = db.execute(
                            "SELECT retained_bytes FROM lifecycle WHERE run_id=?", (rid,)
                        ).fetchone()[0]
                        db.execute("UPDATE storage_usage SET bytes=bytes-? WHERE id=1", (charge,))
                        for table in ("events", "checkpoints", "lifecycle"):
                            db.execute(f"DELETE FROM {table} WHERE run_id=?", (rid,))
                        db.execute("DELETE FROM runs WHERE id=?", (rid,))
                        pending.remove(rid)
                        if interrupt:
                            interrupt("deleted")
                for _, sql in triggers:
                    db.execute(sql)
                audit_before = db.execute(
                    "SELECT COALESCE(SUM(length(CAST(removed AS BLOB))),0) FROM cleanup_log"
                ).fetchone()[0]
                db.execute(
                    "INSERT INTO cleanup_log VALUES (?,?,?)", (uuid.uuid4().hex, self.clock(), canonical(ids))
                )
                db.execute(
                    "DELETE FROM cleanup_log WHERE id NOT IN (SELECT id FROM cleanup_log ORDER BY rowid DESC LIMIT 1000)"
                )
                audit_after = db.execute(
                    "SELECT COALESCE(SUM(length(CAST(removed AS BLOB))),0) FROM cleanup_log"
                ).fetchone()[0]
                db.execute("UPDATE storage_usage SET bytes=bytes+? WHERE id=1", (audit_after - audit_before,))
                if interrupt:
                    interrupt("logged")
                for rid in ids:
                    self._policies.pop(rid, None)
            return result
