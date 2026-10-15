# Implemented architecture

`models.py` defines version-1 event, ticket and API response contracts. `store.py` owns SQLite persistence, sequence allocation, parent checks, immutable snapshot records, chain verification and evidence export. Every append obtains a write transaction before allocating a sequence; foreign keys and unique constraints are enabled. WAL handles concurrency. Connections are scoped to operations; there is no globally shared writable connection.

`sdk.py` provides opt-in capture/redaction, sync/async wrappers and run/span contextvars. Function exceptions are observed and re-raised. A process that dies after run start leaves an incomplete recording; there is no invented successful completion or automatic resume.

`sandbox.py` owns the virtual dispatcher and mutation journal. A `Sandbox` deep-copies input state. Deletion, write and archive compute a journal from their own before/after virtual files. Runtime recording independently compares snapshots and records observed mutations; final reconciliation replays the journal onto initial files.

`runtime.py` contains the explicit document state machine and execution/replay/fork/diff operations. The state transitions consume no wall-clock readings. Full checkpoints precede each tool call and capture driver position, clock, seed, retry budget and count, permissions, files, pending ticket and mock ticket-service state. The seed is retained but current policies consume no random generator.

`api.py` exposes typed local workflows and serves compiled React assets. `cli.py` provides tested commands. `evidence.py` independently checks exported bundles without the producing database; it does not infer authenticity. `benchmark.py` includes authored oracles and measured baselines. React receives all outcomes and diffs from the backend.

## Exact hashing

Canonical JSON: `json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)`, UTF-8 bytes. Hashes are SHA256(domain UTF-8 + NUL + canonical JSON UTF-8). The event-domain payload includes `previous_digest` as a structured fixed-length hex field. The first anchor is 64 zero characters. Domain strings distinguish event, snapshot, payload and evidence-bundle hashes. Newline/whitespace/object-key order cannot alter the canonical representation. Floating-point compatibility is bounded to the JSON values serialized by this Python implementation, not a cross-language canonical JSON standard.

## Scaling boundary

Full snapshots and whole-run verification favor small local workflows. Event retrieval is paginated and the viewer caps loading at 10001 records; it is not virtualized. Listing many large runs repeatedly verifies evidence and may be expensive. Ingress bounds streamed chunks before buffer growth; egress buffers only within its configured cap. Store logical byte counters, finite quotas and cleanup are described in resource_limits.md. These are not physical SQLite/WAL disk limits.

The API validates exact loopback Host, actual bound port and browser Origin. Packaged origins follow the active port rather than a fixed allowlist. A fixed Vite origin requires explicit development opt-in. The CLI never chooses a non-loopback bind.

## M8-R update

See [privacy policy](privacy_policy.md), [retention lifecycle](retention_policy.md), [enforced resource budgets](resource_limits.md), and [security self-review](security_review_M8-R.md). These define the hardened behavior and supersede preview statements about missing capture allowlists, retention and resource bounds. Historical milestone reports remain historical evidence.
