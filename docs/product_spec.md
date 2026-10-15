# Scope and semantics

Mandatory target: local Python SDK + SQLite recorder + resumable deterministic document agent + virtual tools + FastAPI + React debugger. No paid inference, host shell tool, remote deployment, or arbitrary-code replay.

A: playback reads persisted events only. B: offline replay executes the supported driver, consumes recorded observations, recomputes virtual mutations and compares the semantic transcript. C: branch restores the checkpoint immediately before a read-only tool observation, replaces that observation once, and executes the remaining driver with fresh virtual tools. Arbitrary SDK traces are playback-only unless a supported driver exists.

Snapshots include driver position, logical clock, retry count, virtual files, mock records/configuration, deterministic seed. The current driver consumes no stochastic dependencies. Branches refer to shared prefix ancestry rather than copying it and pretending it was executed.

Errors fail closed. Original events and snapshots cannot be updated or deleted through application APIs. Hash chaining detects accidental modification but cannot defend against a database administrator rewriting the whole ledger.
