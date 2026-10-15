# Current known limitations

1. One fixed resumable document driver. Arbitrary trusted Python SDK functions are observable/playback-only; no generic driver registry, live-model continuation or neural determinism guarantee.
2. Fork only a successful read_ticket observation in a complete compatible original. Mutation-result edits, branch replay and branch-of-branch are unsupported. No export re-import adapter.
3. Virtual tools isolate dictionary state. SDK caller-owned code is not sandboxed. Trusted-local unauthenticated API is not hostile-user containment or enterprise multi-tenancy.
4. Metadata-only defaults, scalar allowlists and pre-persistence redaction exist. Explicit content capture can include unknown secrets. Legacy traces are not retroactively sanitized. No encryption or secure erase.
5. Retention and logical resource budgets exist. Physical SQLite/WAL size and OS capacity failures are not fully controlled. Deadlines/cancellation are cooperative; blocked calls may delay recognition.
6. Historical E2/F1 source-recording stalls remain unattributed and were not reproduced in later bounded tests. F2's confirmed quadratic-redaction correction remains regression-tested. No defect-free future reliability guarantee.
7. Intensive diagnostics are opt-in, measured about1.95x source cost in a small M9 sample, and may produce partial evidence after termination. Raw stacks may contain local paths and must stay private.
8. Native Windows Python3.12 was exercised; Linux/macOS/Python3.11 guidance and configured CI are not fresh executed results. Windows Application Control can block mypy; do not bypass OS restrictions.
9. Full snapshots, whole-run verification and non-virtualized event rendering favor small local traces. No live-model or competitor performance claims, human usability study or commercial demand evidence.
10. Hash-chain/unsigned JSON export checks internal consistency, not authenticity or resistance to full administrative chain replacement. Export verification is not proof of a task oracle or computational replay.
11. Source candidate packaging excludes private forensic logs/databases/Git history. Preserved historical Git objects contain local paths; a clean candidate ZIP must not be described as a privacy-clean historical repository.

Current behavior/evidence is mapped in release_claims_matrix.md and the M9-RC report. Historical milestone reports record their original outcomes and are not superseded in place as evidence.
