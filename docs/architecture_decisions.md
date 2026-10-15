# Architecture decisions

1. SQLite standard library with short transactions, WAL and append-only event/checkpoint triggers. JSON canonicalization is sorted keys, UTF-8, compact separators, no NaN; hash domain prefixes separate ledger from snapshots.
2. Complete snapshots, not incremental storage: simpler to verify for small fixtures.
3. A virtual dictionary filesystem and allowlisted dispatcher: no host path adapters or subprocesses.
4. Explicit resumable state machine: no attempt to serialize Python stacks or arbitrary model reasoning.
5. Read-only tool responses are fork points. Replacing mutation results is unsupported because result/state consistency would require additional intervention semantics.
6. FastAPI serves a compiled local React application. Trusted localhost default; request origin/host validation and bounded payloads. No hosted authentication or multi-user guarantees.
7. Contextvars SDK with separate run/span context: concurrent calls preserve parents; persistence uses per-operation SQLite connections.
