# Changelog

## 0.1.0-rc.2 — prepared candidate, not published

- Include the cross-platform diagnostic basename normalization and regression
  tests from main: Windows, POSIX, UNC and mixed stack paths keep the exact module
  allowlist and omit directory prefixes. The 256-frame cap is retained.
- Make Windows API guards visible to cross-platform type checking; run all
  core matrix jobs even if one fails.
- Distinguish current source verification from the historical rc.1 artifact and
  provide a short reviewer entry with explicit replay/privacy/evidence limits.
- Align Python and frontend package versions at rc.2. No new agent driver,
  scientific result, authenticity guarantee or privacy-policy weakening is added.

This candidate is prepared on a separate branch for installation and package
verification. Existing rc.1 tags/assets are unchanged. Publication requires an
explicit owner decision after review of the candidate's actual evidence.

Support remains bounded to the declared scripted document workflow. Historical
E2/F1 stalls remain unattributed; unsigned evidence establishes consistency, not
authenticity; SDK wrappers do not sandbox host effects. Dependency bootstrap,
physical SQLite size and cooperative cancellation limitations remain.

## 0.1.0-rc.1 — local candidate preparation

- Replace fixed localhost origin ports with exact validated loopback authority/current bound-port checks. Vite5173 requires explicit opt-in; invalid CLI ports reject clearly.
- Label SDK tool events separately from the supported virtual document workspace; absent/partial state is not fabricated.
- Reconcile privacy, retention, streamed limits, cooperative execution and platform documentation. Add release claims/evidence mapping.
- Select and scan source distribution contents; exclude private forensic logs, databases and historical Git objects. Preserve original audit evidence/history locally.
- Retain existing replay/branch/state/privacy/retention/quota/F2 regressions and independently retest the original M9 cases against the corrected implementation.

Known limitations: one deterministic scripted driver; no arbitrary LLM replay or host sandbox; E2/F1 historical stalls remain unattributed; optional diagnostics incur material overhead; Windows3.12 verified only; no human/market validation. Local RC tag is conditional on completed verification. No public publication or stable v0.1.0 tag is authorized by this preparation milestone.
