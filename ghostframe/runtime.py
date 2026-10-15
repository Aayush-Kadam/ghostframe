"""Resumable deterministic driver, computational replay, and genuine continuation branches."""

from __future__ import annotations

import copy
import threading
import time
from difflib import SequenceMatcher

from .boundary import request_cancelled
from .models import GFError, canonical, digest
from .policies import CapturePolicy
from .sandbox import Sandbox, state_diff
from .store import Store

VERSION = "document-agent.v1"


def initial_state(fixture: dict) -> dict:
    return {
        "pc": "ticket",
        "step": 0,
        "logical_clock": 0,
        "seed": fixture.get("seed", 0),
        "retry": 0,
        "budget": fixture.get("retry_budget", 2),
        "ticket": None,
        "files": copy.deepcopy(fixture["files"]),
        "permissions": copy.deepcopy(fixture.get("permissions", {})),
        "mock": {
            "ticket": copy.deepcopy(fixture["ticket"]),
            "attempt": 0,
            "failures": fixture.get("failures", []),
            "approval": fixture.get("approval", False),
        },
        "outcome": None,
    }


class DocumentDriver:
    """Program counter + serializable state replaces unsafe stack serialization."""

    version = VERSION

    def action(self, state: dict) -> tuple[str, dict] | None:
        pc = state["pc"]
        if pc == "ticket":
            return "read_ticket", {"ticket_id": "task-001"}
        if pc == "approval":
            return "request_approval", {"path": state["ticket"]["target"]}
        if pc == "apply":
            t = state["ticket"]
            if t["action"] == "noop":
                return "list_files", {}
            tool = {"delete": "delete_file", "write": "write_file", "archive": "archive_file"}[t["action"]]
            return tool, {"path": t["target"], "content": t["content"], "approved": t["approved"]}
        return None

    def observe(self, state: dict, tool: str, result: dict):
        if tool == "read_ticket":
            if "error" in result:
                if result["error"] in {"TIMEOUT", "TRANSIENT"} and state["retry"] < state["budget"]:
                    state["retry"] += 1
                else:
                    state["pc"], state["outcome"] = "done", {"error": result["error"]}
            else:
                try:
                    state["ticket"] = Sandbox(state).validate_ticket(result)
                except GFError as exc:
                    state["pc"], state["outcome"] = "done", {"error": exc.code}
                else:
                    state["pc"] = (
                        "approval"
                        if state["permissions"].get(state["ticket"]["target"]) == "approval"
                        else "apply"
                    )
        elif tool == "request_approval":
            if result["approved"]:
                state["ticket"]["approved"] = True
                state["pc"] = "apply"
            else:
                state["pc"], state["outcome"] = "done", {"error": "POLICY_DENIED"}
        else:
            state["pc"], state["outcome"] = "done", result
        state["logical_clock"] += 1
        state["step"] += 1


def oracle(fixture: dict, state: dict) -> dict:
    """Expectations are fixture-authored, never copied from generated execution."""
    expected = fixture["goal_files"]
    return {
        "task_correct": state["files"] == expected,
        "result": state["outcome"],
        "final_files": state["files"],
    }


SEMANTIC_KINDS = {
    "TOOL_CALL_REQUESTED",
    "TOOL_CALL_COMPLETED",
    "TOOL_CALL_FAILED",
    "SIDE_EFFECT_RECORDED",
    "POLICY_DENIED",
    "AGENT_STEP_COMPLETED",
    "RUN_COMPLETED",
    "RUN_FAILED",
}


def semantic(events: list[dict]) -> list[dict]:
    return [
        {k: e[k] for k in ("kind", "tool", "step", "payload", "status")}
        for e in events
        if e["kind"] in SEMANTIC_KINDS
    ]


class Engine:
    def __init__(self, store: Store):
        self.store, self.driver = store, DocumentDriver()
        self.cancelled = threading.Event()

    def _execute(
        self,
        fixture: dict,
        state: dict,
        provenance: str = "RECORDED",
        parent: dict | None = None,
        replay_events: list[dict] | None = None,
        replacement: dict | None = None,
    ) -> str:
        cancellation = request_cancelled.get()
        box = Sandbox(state, limits=self.store.limits)
        rid = self.store.create(
            {
                "name": fixture["name"],
                "fixture": fixture,
                "driver_version": VERSION,
                "provenance": provenance,
                **(parent or {}),
            },
            policy=CapturePolicy(mode="synthetic_fixture", max_bytes=self.store.limits.checkpoint_bytes),
        )
        self.store.append(rid, "RUN_STARTED", {"driver": VERSION}, provenance=provenance)
        source_completions = [
            e for e in (replay_events or []) if e["kind"] in {"TOOL_CALL_COMPLETED", "TOOL_CALL_FAILED"}
        ]
        if parent and provenance == "REEXECUTED_SCRIPTED":
            self.store.append(rid, "BRANCH_CREATED", parent, provenance=provenance)
        start_files = copy.deepcopy(state["files"])
        used = 0
        started = time.monotonic()
        try:
            for _ in range(self.store.limits.steps):
                if self.cancelled.is_set() or (cancellation is not None and cancellation.is_set()):
                    raise GFError("EXECUTION_CANCELLED", "Controlled execution cancelled")
                if time.monotonic() - started > self.store.limits.seconds:
                    raise GFError(
                        "BRANCH_TIMEOUT" if provenance == "REEXECUTED_SCRIPTED" else "EXECUTION_TIMEOUT",
                        "Execution time budget exceeded",
                    )
                action = self.driver.action(box.state)
                if action is None:
                    break
                tool, args = action
                cp = self.store.checkpoint(rid, box.state)
                self.store.append(
                    rid,
                    "STATE_CHECKPOINT_CREATED",
                    {"state_digest": digest(box.state)},
                    checkpoint=cp,
                    step=box.state["step"],
                    provenance=provenance,
                )
                request = self.store.append(
                    rid,
                    "TOOL_CALL_REQUESTED",
                    args,
                    tool=tool,
                    step=box.state["step"],
                    checkpoint=cp,
                    provenance=provenance,
                )
                before = copy.deepcopy(box.state["files"])
                if replay_events is not None:
                    if used >= len(source_completions):
                        raise GFError(
                            "EVENT_MISMATCH",
                            "Replay produced an extra tool action",
                            {"step": box.state["step"]},
                        )
                    expected = source_completions[used]
                    original_request = next(e for e in replay_events if e["event_id"] == expected["parent"])
                    if tool != expected["tool"] or args != original_request["payload"]:
                        raise GFError(
                            "EVENT_MISMATCH",
                            "Tool signature diverged",
                            {
                                "step": box.state["step"],
                                "expected": original_request["payload"],
                                "actual": args,
                            },
                        )
                    # External read observations are recorded; local mutation transition is recomputed and checked.
                    if tool in {"read_ticket", "request_approval"}:
                        result = copy.deepcopy(expected["payload"])
                        if tool == "read_ticket":
                            box.state["mock"]["attempt"] += 1
                    else:
                        try:
                            result = box.call(tool, args)
                        except GFError as exc:
                            if exc.code == "FILESYSTEM_QUOTA_EXCEEDED":
                                raise
                            result = {"error": exc.code}
                        if result != expected["payload"]:
                            raise GFError(
                                "STATE_MISMATCH", "Virtual tool effect diverged", {"step": box.state["step"]}
                            )
                    used += 1
                elif replacement is not None and used == 0:
                    if tool != "read_ticket":
                        raise GFError("UNSUPPORTED_FORK", "Checkpoint is not before read_ticket")
                    result = copy.deepcopy(replacement)
                    box.state["mock"]["attempt"] += 1
                    self.store.append(
                        rid,
                        "INTERVENTION_APPLIED",
                        {
                            "type": "REPLACE_TOOL_RESULT",
                            "replacement": result,
                            "source_event": parent["source_event"] if parent else None,
                        },
                        tool=tool,
                        step=box.state["step"],
                        parent=request["event_id"],
                        provenance=provenance,
                    )
                    used += 1
                else:
                    try:
                        result = box.call(tool, args)
                    except GFError as exc:
                        result = {"error": exc.code}
                if result.get("error") == "FILESYSTEM_QUOTA_EXCEEDED":
                    raise GFError(
                        "FILESYSTEM_QUOTA_EXCEEDED", "Virtual tool operation exceeded its resource budget"
                    )
                status = "ERROR" if "error" in result else "OK"
                completion = self.store.append(
                    rid,
                    "TOOL_CALL_FAILED" if status == "ERROR" else "TOOL_CALL_COMPLETED",
                    result,
                    parent=request["event_id"],
                    tool=tool,
                    step=box.state["step"],
                    checkpoint=cp,
                    status=status,
                    provenance=provenance,
                )
                if result.get("error") in {"POLICY_DENIED", "APPROVAL_REQUIRED"}:
                    self.store.append(
                        rid,
                        "POLICY_DENIED",
                        result,
                        tool=tool,
                        parent=completion["event_id"],
                        step=box.state["step"],
                        provenance=provenance,
                    )
                for change in state_diff(before, box.state["files"]):
                    self.store.append(
                        rid,
                        "SIDE_EFFECT_RECORDED",
                        change,
                        parent=completion["event_id"],
                        tool=tool,
                        step=box.state["step"],
                        provenance=provenance,
                    )
                self.driver.observe(box.state, tool, result)
                self.store.append(
                    rid,
                    "AGENT_STEP_COMPLETED",
                    {"state": copy.deepcopy(box.state)},
                    step=box.state["step"],
                    provenance=provenance,
                )
            else:
                raise GFError(
                    "REPLAY_STEP_LIMIT_EXCEEDED" if replay_events is not None else "EXECUTION_TIMEOUT",
                    "Driver exceeded logical step budget",
                )
            if time.monotonic() - started > self.store.limits.seconds:
                raise GFError(
                    "BRANCH_TIMEOUT" if provenance == "REEXECUTED_SCRIPTED" else "EXECUTION_TIMEOUT",
                    "Execution time budget exceeded",
                )
            if self.cancelled.is_set() or (cancellation is not None and cancellation.is_set()):
                raise GFError("EXECUTION_CANCELLED", "Controlled execution cancelled")
            if replay_events is not None and used != len(source_completions):
                raise GFError("EVENT_MISMATCH", "Replay omitted recorded tool actions")
            reconciled = copy.deepcopy(start_files)
            for entry in box.journal:
                if entry["operation"] == "delete":
                    reconciled.pop(entry["path"], None)
                else:
                    reconciled[entry["path"]] = entry["after"]
            if reconciled != box.state["files"]:
                raise GFError("SIDE_EFFECT_MISMATCH", "Mutation journal does not reconstruct final state")
            self.store.checkpoint(rid, box.state)
            final_outcome = {**oracle(fixture, box.state), "journal": box.journal, "journal_reconciled": True}
            if replay_events is not None:
                expected_semantic = semantic(replay_events)
                actual_semantic = semantic(self.store.events(rid)) + [
                    {
                        "kind": "RUN_COMPLETED",
                        "tool": None,
                        "step": None,
                        "payload": final_outcome,
                        "status": "OK",
                    }
                ]
                mismatch = next(
                    (i for i, (a, b) in enumerate(zip(expected_semantic, actual_semantic)) if a != b), None
                )
                if mismatch is None and len(expected_semantic) != len(actual_semantic):
                    mismatch = min(len(expected_semantic), len(actual_semantic))
                if mismatch is not None:
                    raise GFError(
                        "EVENT_MISMATCH",
                        "Semantic state or outcome diverged",
                        {
                            "index": mismatch,
                            "expected": expected_semantic[mismatch]
                            if mismatch < len(expected_semantic)
                            else None,
                            "actual": actual_semantic[mismatch] if mismatch < len(actual_semantic) else None,
                        },
                    )
            self.store.append(
                rid,
                "RUN_COMPLETED",
                final_outcome,
                provenance=provenance,
            )
            return rid
        except BaseException as exc:
            self.store.fail(rid, exc.code if isinstance(exc, GFError) else "EXECUTION_FAILED")
            if isinstance(exc, GFError):
                exc.details = {"failed_run_id": rid, "evidence": exc.details}
            raise

    def run(self, fixture: dict) -> str:
        if fixture.get("synthetic") is not True:
            raise GFError(
                "SYNTHETIC_OPT_IN_REQUIRED", "This driver accepts explicitly marked synthetic fixtures only"
            )
        self.store.limits.check(fixture, self.store.limits.checkpoint_bytes)
        with self.store.operation():
            return self._execute(fixture, initial_state(fixture))

    def _eligible(self, rid: str) -> tuple[dict, list[dict]]:
        valid = self.store.verify(rid)
        meta, events = self.store.metadata(rid), self.store.events(rid)
        if events[-1]["kind"] != "RUN_COMPLETED":
            raise GFError("MISSING_CAPTURE", "Failed runtime has no complete supported execution")
        if not valid["complete"] or not all(e["capture_complete"] for e in events):
            raise GFError("MISSING_CAPTURE", "Trace is incomplete or required content was not captured")
        if meta.get("driver_version") != VERSION:
            raise GFError("UNSUPPORTED_DRIVER", "No compatible resumable driver exists")
        fixture = meta.get("fixture")
        if not isinstance(fixture, dict) or any(
            k not in fixture for k in ("files", "ticket", "name", "goal_files")
        ):
            raise GFError("MISSING_CAPTURE", "Replay input fixture is unavailable")
        if meta.get("provenance") == "REEXECUTED_SCRIPTED":
            raise GFError("UNSUPPORTED_FORK", "Branch-of-branch and branch replay are outside this version")
        return meta, events

    def replay(self, rid: str) -> dict:
        with self.store.operation(rid):
            return self._replay(rid)

    def _replay(self, rid: str) -> dict:
        meta, events = self._eligible(rid)
        replay = self._execute(
            meta["fixture"],
            initial_state(meta["fixture"]),
            "REPLAYED_DETERMINISTICALLY",
            {"parent_id": rid},
            replay_events=events,
        )
        left, right = semantic(events), semantic(self.store.events(replay))
        mismatch = next((i for i, (a, b) in enumerate(zip(left, right)) if a != b), None)
        if len(left) != len(right) and mismatch is None:
            mismatch = min(len(left), len(right))
        if mismatch is not None:
            raise GFError(
                "EVENT_MISMATCH",
                "Semantic transcript diverged",
                {
                    "index": mismatch,
                    "replay_id": replay,
                    "expected": left[mismatch] if mismatch < len(left) else None,
                    "actual": right[mismatch] if mismatch < len(right) else None,
                },
            )
        return {
            "status": "REPLAY_SUCCESS",
            "provenance": "REPLAYED_DETERMINISTICALLY",
            "run_id": replay,
            "source_id": rid,
            "semantic_events": len(left),
        }

    def fork(
        self,
        rid: str,
        event_id: str,
        replacement: dict,
        label: str = "Controlled intervention",
        note: str = "",
    ) -> dict:
        with self.store.operation(rid):
            return self._fork(rid, event_id, replacement, label, note)

    def _fork(
        self,
        rid: str,
        event_id: str,
        replacement: dict,
        label: str = "Controlled intervention",
        note: str = "",
    ) -> dict:
        self.store.limits.check(replacement)
        self.store.limits.check({"label": label, "note": note})
        meta, events = self._eligible(rid)
        event = next((e for e in events if e["event_id"] == event_id), None)
        if not event or event["kind"] != "TOOL_CALL_COMPLETED" or event["tool"] != "read_ticket":
            raise GFError("UNSUPPORTED_FORK", "Only successful read_ticket results are editable")
        if not event["checkpoint"]:
            raise GFError("CHECKPOINT_MISSING", "No resumable checkpoint")
        state = self.store.restore(event["checkpoint"], rid)
        payload = Sandbox(state, limits=self.store.limits).validate_ticket(replacement)
        before = self.store.export(rid)["digest"]
        branch = self._execute(
            meta["fixture"],
            state,
            "REEXECUTED_SCRIPTED",
            {
                "parent_id": rid,
                "source_event": event_id,
                "source_checkpoint": event["checkpoint"],
                "fork_step": event["step"],
                "label": label,
                "note": note,
                "shared_prefix_end": event["seq"] - 1,
            },
            replacement=payload,
        )
        if before != self.store.export(rid)["digest"]:
            raise GFError("PARENT_MUTATED", "Source history changed during branching")
        return {
            "branch_id": branch,
            "status": "BRANCH_SUCCESS",
            "provenance": "REEXECUTED_SCRIPTED",
            "comparison": self.compare(rid, branch),
        }

    def compare(self, original: str, branch: str) -> dict:
        self.store.verify(original)
        self.store.verify(branch)
        a, b = self.store.summary(original), self.store.summary(branch)
        if a["outcome"] is None or b["outcome"] is None:
            raise GFError("INCOMPLETE_CAPTURE", "Comparison requires completed task outcomes")
        ae, be = self.store.events(original), self.store.events(branch)
        fork_step = b.get("fork_step", 0)
        aa = [e for e in ae if e["kind"] == "TOOL_CALL_REQUESTED" and (e["step"] or 0) >= fork_step]
        ba = [e for e in be if e["kind"] == "TOOL_CALL_REQUESTED"]
        keys = lambda es: [canonical({"tool": e["tool"], "payload": e["payload"]}) for e in es]
        alignment = [
            {
                "operation": op,
                "original": [x["payload"] for x in aa[i:j]],
                "branch": [x["payload"] for x in ba[k:l]],
                "confidence": "exact-signature" if op == "equal" else "sequence-only",
            }
            for op, i, j, k, l in SequenceMatcher(None, keys(aa), keys(ba), autojunk=False).get_opcodes()
        ]
        return {
            "original_id": original,
            "branch_id": branch,
            "original_outcome": a["outcome"],
            "branch_outcome": b["outcome"],
            "state_diff": state_diff(a["outcome"]["final_files"], b["outcome"]["final_files"]),
            "actions": alignment,
            "source_event": b.get("source_event"),
            "source_checkpoint": b.get("source_checkpoint"),
            "first_observed_divergence": b.get("source_event")
            if any(x["operation"] != "equal" for x in alignment) or a["outcome"] != b["outcome"]
            else None,
            "continuation_changed": any(x["operation"] != "equal" for x in alignment)
            or a["outcome"]["final_files"] != b["outcome"]["final_files"],
            "shared_prefix_end": b.get("shared_prefix_end"),
            "limitations": "Action alignment after the fork is sequence-based; first divergence is not proof of root cause.",
            "original_integrity": a["integrity"],
            "branch_integrity": b["integrity"],
        }
