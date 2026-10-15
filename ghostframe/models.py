"""Versioned contracts and domain-separated canonical integrity."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value: Any, domain: str = "ghostframe.snapshot.v1") -> str:
    return hashlib.sha256(domain.encode() + b"\0" + canonical(value).encode("utf-8")).hexdigest()


class GFError(Exception):
    def __init__(self, code: str, message: str, details: Any = None):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details

    def json(self) -> dict:
        return {"code": self.code, "message": self.message, "details": self.details}


class Event(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    event_id: str
    run_id: str
    seq: int = Field(ge=0)
    kind: Literal[
        "RUN_STARTED",
        "RUN_COMPLETED",
        "RUN_FAILED",
        "TOOL_CALL_REQUESTED",
        "TOOL_CALL_COMPLETED",
        "TOOL_CALL_FAILED",
        "STATE_CHECKPOINT_CREATED",
        "SIDE_EFFECT_RECORDED",
        "AGENT_STEP_COMPLETED",
        "INTERVENTION_APPLIED",
        "BRANCH_CREATED",
        "POLICY_DENIED",
    ]
    parent: str | None = None
    timestamp: str
    monotonic_ns: int
    actor: str = "scripted-document-agent"
    tool: str | None = None
    step: int | None = None
    payload: Any = None
    payload_hash: str
    status: str = "OK"
    provenance: str = "RECORDED"
    capture_complete: bool = True
    checkpoint: str | None = None
    previous_digest: str
    event_digest: str


class Ticket(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action: Literal["delete", "write", "archive", "noop"]
    target: str = Field(min_length=1, max_length=256)
    content: str = Field(default="", max_length=8192)
    approved: bool = False
    note: str = Field(default="", max_length=8192)


class ForkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: str = Field(max_length=80)
    replacement: Ticket
    label: str = Field(default="Controlled intervention", max_length=100)
    note: str = Field(default="", max_length=500)


class IntegrityResult(BaseModel):
    valid: bool
    complete: bool | None = None
    events: int | None = None
    head: str | None = None
    status: str


class RunSummary(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    name: str
    created: str
    event_count: int
    status: str
    provenance: str
    replay_eligible: bool
    integrity: IntegrityResult
    outcome: dict | None


class EventPage(BaseModel):
    events: list[Event]
    total: int
    offset: int


class ReplayResult(BaseModel):
    status: Literal["REPLAY_SUCCESS"]
    provenance: Literal["REPLAYED_DETERMINISTICALLY"]
    run_id: str
    source_id: str
    semantic_events: int


class ComparisonResult(BaseModel):
    original_id: str
    branch_id: str
    original_outcome: dict
    branch_outcome: dict
    state_diff: list[dict]
    actions: list[dict]
    source_event: str | None
    source_checkpoint: str | None
    first_observed_divergence: str | None
    continuation_changed: bool
    shared_prefix_end: int | None
    limitations: str
    original_integrity: IntegrityResult
    branch_integrity: IntegrityResult


class BranchResult(BaseModel):
    branch_id: str
    status: Literal["BRANCH_SUCCESS"]
    provenance: Literal["REEXECUTED_SCRIPTED"]
    comparison: ComparisonResult


class EvidenceBundle(BaseModel):
    bundle: dict
    digest: str
