> Historical assessment: use release_claims_matrix.md and milestones/M9-RC.md for current scope/results.

# M8-R self-challenge and security review

This is an internal adversarial review, not an independent M9-R assessment. Expected adverse outcomes were recorded before implementation in M8-R-protocol.md. The new test file is separate from the 40 existing development/regression fixture scenarios.

Counterexamples found and addressed: SDK-only filtering left Store paths unrestricted; capture policy was centralized before persistence. Requests were fully buffered before size checks; chunk and structural budgets now precede processing. SQLite handles survived context-manager exit on Windows; connections now close explicitly. Unsupported event/schema errors could echo values; supported errors now contain generic messages. Missing fixture input could cause an untyped replay error; eligibility and execution both reject it honestly. Existing capture/retention decisions could change on reopening; capture falls back conservatively and retention is snapshotted per run. Per-operation whole-store scans caused unnecessary overhead; transactional accounting now avoids them without changing quotas.

Adversarial evidence includes synthetic secret canaries, undeclared fields/subtrees, legacy histories, retention dependencies/pinning/active operations, exception and abrupt-process cleanup interruption at three points, byte-counter rollback, low quotas, corrupted/missing replay inputs, concurrent branch admission, process-lease recovery, chunked bodies, compressed-input rejection, receipt timeouts, client disconnect, response limits, virtual filesystem isolation and Windows unlink/Unicode paths. Source export digests and independent fixture expectations remain invariant across replay/branching.

Known boundaries: trusted localhost, not multi-user hosted authentication; no encryption or secure erasure; best-effort pattern redaction; no arbitrary-agent/model replay; SDK decorators do not sandbox caller code; timeout recognition is cooperative; administrator edits to SQLite/counters are outside the supported boundary. PID reuse or denied process inspection may conservatively retain a lease. Large bounded UI histories can need later rendering optimization. M9-R external review remains mandatory before stable v0.1.

Historical baseline failures and provisional test/benchmark results are retained in the preflight/final report. No failing security case is suppressed to award a pass. Dependency findings are known-advisory checks, not a proof of safety.

Final self-challenge additions: duplicate HTTP headers now count individually against metadata budgets; Unicode intervention JSON is read explicitly as UTF-8; raw HTTP access logs are disabled by default; and checkpoint/source identifiers must name owned evidence rather than arbitrary strings. Windows virtual reserved names stay dictionary keys and are never resolved on the host.

Configuration opt-in flags require actual booleans; strings such as false cannot accidentally enable full capture or expiry. Browser assertion counts now use runtime execution rather than static source-site counts, excluding skipped optional branches.
