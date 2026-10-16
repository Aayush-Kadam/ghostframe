# GhostFrame v0.1.0-rc.1 — First Public Preview

This pre-release is a local-first recorder and counterfactual debugger for supported deterministic AI-agent workflows. It requires no model key or paid service.

## Features

- Python event-recording SDK and structured SQLite execution histories.
- Recorded playback without tool execution; deterministic scripted-agent replay.
- Checkpoint restoration, controlled tool-result intervention, genuine counterfactual branch re-execution and side-effect comparison.
- Local FastAPI backend and React debugger, including default and custom-port support.
- Metadata-only defaults, scalar capture allowlists, best-effort redaction, retention and resource bounds.

## Verification

Historical M9-RC qualification: 192 Python tests, 14 frontend tests and 55 browser assertions passed; 38/38 frozen M9 cases passed on the corrected commit; 120/120 canonical attempts, 15/15 branch cases and 339/339 checkpoint restorations passed. Original M9 recorded 37/38 before the custom-port correction; that result remains preserved.

These are controlled test results, not guarantees of arbitrary-agent correctness. PUBLICATION-01 fresh extraction independently passed 98 critical Python tests and 14 frontend tests, dependency consistency, the deterministic demo and the frontend build. Separate real-browser checks on both ports are recorded in the local publication report.

## Scope and limitations

Guaranteed offline re-execution applies only to complete compatible original document-agent.v1 traces. Generic SDK recordings support playback, not arbitrary-function re-execution. One supported scripted driver and one controlled observation intervention are implemented. There is no universal deterministic replay of arbitrary LLM agents or guarantee of repeating stochastic model decisions.

The server is unauthenticated and trusted-local: no enterprise multi-user security or general untrusted host-code sandbox guarantee. Capture redaction is best effort; data is not encrypted at rest. Historical E2/F1 recording stalls remain unattributed, not fixed. Detailed diagnostic mode measured approximately 1.95x recording cost in a small controlled sample. Native Windows Python 3.12 was executed; other-platform guidance and CI configuration do not establish equivalent observed qualification. No commercial demand or debugging-time benefit has been proven.

## Audit transparency and prior art

M9 used prospectively frozen independent-style fixtures and expected outcomes in the same AI-assisted Work session. It was not a third-party human security certification. LangGraph checkpoint replay and modified-state branches, Temporal, and mature tracing tools are prior art; GhostFrame claims a bounded offline engineering integration, not first-ever agent time travel.

MIT licensed. Compiled frontend attribution is in THIRD_PARTY_NOTICES.md. See README.md, SECURITY.md and docs/limitations.md.

## Release asset

Exact sanitized candidate: GhostFrame_v0.1.0-rc.1_Source.zip

SHA-256: `ee37a1bb7b7a756455e3a5220aa3c4bad279ca9b0d3d7802bc3335ba4c888069`

The asset retains the original candidate manifest. The public root adds presentation-only README, ignore-rule and release-note changes; implementation files are unchanged. No private Git history is included.
