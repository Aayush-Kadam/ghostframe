# Semantic property tests and performance evidence

M3 run 38958964777 on Windows/Python 3.12 failed with 206 passed and one
Hypothesis FlakyFailure. The same `delete`, `ca` input took 31.562 seconds on
the initial run and 1.330 seconds on retry. Its semantic assertions did not
produce a stable counterexample; the exact input also passed locally.
The source test performs recording, SQLite I/O, replay and export consistency.
The root cause of that particular runner pause remains unattributed.

The five-second per-example deadline was not a documented runtime guarantee.
This semantic property now keeps all fifteen generated examples and every
assertion without a wall-clock deadline. CI separately caps each full core job
at twenty minutes, and runtime quotas/cancellation behavior are unchanged.
This explicitly removes a flaky test timing condition; it does not establish
that the observed long pause is fixed or that latency is bounded to five seconds.
Performance observations belong in the separately reported benchmark, which
currently supplies measurements rather than an acceptance SLO.

The failed run is retained. A new full matrix must pass, including the reviewer,
Ruff and mypy steps previously skipped after the failure. No retry-only success,
xfail, skipped semantic case or relaxed product privacy/security policy is used.
