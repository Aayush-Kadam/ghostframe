# Release claims reconciliation

Current release-facing statements below supersede earlier preview descriptions. Historical milestones and original failed audit evidence remain preserved locally and are not used as proof of a new passing result.

| Document/location | Claimed behavior / old conflict | Actual behavior | Evidence / necessary correction |
|---|---|---|---|
| README modes; replay_semantics | Playback, replay and branching distinct | Stored browsing does not execute; compatible driver recomputes mutations; branch changes one read observation | Frozen M9 A04-A06/D02-D05/E01 and runtime regressions; no arbitrary LLM time travel |
| README security; threat_model | Old paragraph denied automatic retention/allowlisting | Store applies metadata-only defaults/scalar allowlists and transactional dependency-aware retention | M9 C01/C05/E02/E07 and hardening tests; obsolete denial removed |
| architecture scaling | Old after-read request-cap description | Ingress counts chunks before growth; response/export budgets and logical quotas | hardening/boundary tests and M9 C02/C06/C07; physical disk caveat retained |
| API/CLI; README ports | Fixed-origin list broke custom ports | Exact loopback Host plus actual bound port, same-origin HTTP; explicit Vite opt-in only | tests/test_m9rc.py and original M9 D04 retest; no wildcard trust |
| UI heading/state tab | SDK trace called a virtual workspace | Generic tool events and no fabricated snapshot; virtual state only for actual supported driver data | frontend contracts and actual API/browser label cases |
| privacy_policy | Metadata-only versus explicit capture | Sanitization occurs before persistence; allowed unknown secrets can still leak | canary DB/WAL/export tests; no universal redaction guarantee |
| resource_limits | Deadlines and quotas | Cooperative checks, logical bytes; no arbitrary function preemption or exact physical disk cap | cancellation, quota and forced worker tests |
| architecture/replay_semantics | Event history integrity | Hash-chain consistency/SQLite triggers, not authenticity or immunity to an administrative rewrite | corruption and evidence tests; no cryptographic-immutability claim |
| threat_model/SDK example | Virtual isolation | Bundled dictionary dispatcher only; caller-owned decorated functions can act on host | sandbox path tests and M9 D04 counter; no host-code sandbox claim |
| windows_verification | Old untested-Windows language | Native Windows3.12 demonstrated; other OS/Python3.11 not newly run | fresh extracted installation and native verification logs |
| limitations; diagnostics | Reliability | E2/F1 historical gaps remain unattributed, later bounded nonreproduction; F2 correction preserved; detailed diagnostics intrusive/optional | original M9 evidence and existing redaction test, no future-perfect reliability claim |
| README prior art | Originality/market | Engineering integration, established tracing/replay/checkpoint forks | M9 prior-art review; LangGraph acknowledged; no commercial demand proof |
| Release privacy | Clean ZIP versus historical repository | Candidate excludes private logs/DBs/history and is scanned; old Git objects remain unchanged | scripts/release_scan.py and packaging report; no clean-history claim |

Central outcome claims require completed tests on the remediation commit; see docs/milestones/M9-RC.md. Unsupported optional functionality is not redefined as a release blocker. The original 38-case denominator is preserved: M9 was37/38; new results must be explicitly attributed to the corrected commit.
