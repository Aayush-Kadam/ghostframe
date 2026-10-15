# GhostFrame M9-RC release-candidate assessment

Date: 2026-10-15, Asia/Calcutta. Local preparation only; no publication, deployment, remote push or stable tag.

## A. Verdict

**PASS — RELEASE CANDIDATE READY.** All four mandatory product P2 findings are corrected for the proposed source distribution. No unresolved confirmed P0/P1 remains within the performed scope. Historical risks and scope limits are retained. This is same-session automated engineering/audit work, not independent human certification.

## B. Four audit findings

| Finding | Root cause | Fix | Retest | Status |
|---|---|---|---|---|
| Nondefault port | Fixed8765/5173 origins | Validated exact loopback Host/current bound port, same-origin policy, explicit Vite opt-in | Original8879 browser failure now passes; default/alternate assets, reads, writes, branch, reload; invalid Host/Origin/port reject | RESOLVED |
| Contradictory docs | Old hardening denials beside updates | Reconciled current documents and release_claims_matrix.md | Manual claims-to-implementation/test review | RESOLVED |
| Machine information in handoff | Private forensic artifacts included | Sanitize copied prefixes/hostnames; select portable source and exclude private history/logs/DBs; new genuine screenshots | Selected source and final archive privacy scans, manifest/extraction checks | RESOLVED for distribution |
| SDK virtual heading | Unconditional document-workspace label | Driver/provenance/actual state-based UI; no inferred missing snapshot |14 actual-API label assertions, frontend contracts, original branch comparison | RESOLVED |

Details and focused commit references: docs/M9-RC-remediation.md. Original M9 verdict and37/38 failure remain preserved; no historical baseline is relabeled38/38.

## C. Full verification

| Check | Actual result |
|---|---|
| Full native Python suite |192 passed; original 167 unchanged plus 25 new targeted cases;0 failed/error/skip |
| Parent-only statement coverage |84.64250%,1681/1986; no worker-subprocess collection or exclusions; not the older combined-worker90.77% |
| Frontend contracts / production build |14/14 / PASS |
| Existing browser / new label / frozen custom-port assertions |27 / 14 / 14 = 55 actually executed assertion calls;0 page errors |
| Frozen original M9 eligible suite |38/38 on corrected implementation;0 failed/invalid/unsupported; includes eight E cases |
| Canonical recording / replay / end-to-end |120/120 each; one declared warmup outside denominator |
| Branch / checkpoint restoration |15/15 /339/339 |
| Security/privacy/retention/quota/F2 |Existing suite plus 25 bound-origin/port regressions passed |
| Ruff / configured native mypy |PASS / PASS,15 source files; normal module invocation, no bypass |
| Clean source extraction |Manifest/CRC/19 implementation+asset comparisons pass |
| Fresh extracted install |New isolated environment, noneditable source install, pip check, real demo PASS |
| Extracted full suite / frontend build |192 passed in 181.29s / PASS from lockfile |

Native Windows build 26300.9711/display26H2, Python 3.12.14, Node 24.19.0, Chromium 156.0.8078.4. Other OS/Python3.11 results are not inferred. The main suite completed in 205.40s while other bounded checks ran; timings are not an isolated-machine speed claim. One upstream Starlette/httpx deprecation warning remains.

The frozen audit retest is attributed to723a7b9c97604856b8f890b308207584fb07463e; clean source implementation to 6c0500d and its descendants. Between those, API regex flag spelling changed from re.I to its identical re.IGNORECASE constant; extraction independently passed the complete192 cases after that cleanup. Final runtime/assets match the clean tested implementation; release-only docs/metadata and selection changes are separately verified by final package install/manifest checks. Raw canonical benchmark execution was outside a Git checkout and truthfully records git_commit=uncommitted; release-summary.json supplies its qualification context rather than fabricating benchmark metadata.

Recording median/p95/max192.431/271.803/336.250ms; replay331.794/446.461/520.805ms. No speedup/rare-failure probability claim. Side-effect accounting and parent preservation passed. Canonical source/replay clocks remain separate.

## D. Security

Exact Host authorities accept only localhost,127.0.0.1 or bracketed loopback IPv6 with a valid port that matches the ASGI server's actual bound port. The synthetic in-process testserver address is not a network Host exception. Attacker lookalikes, userinfo, wrong ports, remote origins and cross-local-port writes reject. Origin:null rejects. Packaged default does not trust Vite5173; explicit opt-in trusts only its fixed two local origins. No wildcard CORS, removed checks, public bind, new enterprise auth or arbitrary host execution adapter.

Both8765 and8879 work in actual browser/API tests; unauthorized requests never create runs. CLI rejects0,65536,noninteger and fractional ports before opening storage. Trusted non-browser local clients may omit Origin; this is not protection against another local process. No public-host/multi-user security claim.

## E. Privacy

Selected-source and final-ZIP scans cover identifying user homes/workspaces, common machine hostnames, private-key patterns and archive paths, plus manual review of meaningful matches and eight genuine screenshots. No confirmed unnecessary sensitive local information found in the proposed distribution within this scan. Synthetic canaries/virtual paths, versions, relative filenames and technical hashes are retained.

Private evidence and original failures remain local. Historical scan reviewed 908 text objects and found 44 pattern occurrences in preserved history;0 private-key pattern hits. No Git history was rewritten. Identifying metadata is not treated as an exposed password. **The candidate ZIP excludes .git/history; a clean ZIP does not imply clean historical Git.** A future public-history proposal requires its own owner scope decision.

New clean environment upgrades bootstrap pip normally from trusted PyPI to 26.2.1; per-version advisory metadata reports0. The old M9 environment/pip risk remains a preserved historical/environment note, not silently overwritten. Runtime dependency and secret scans are scoped checks, not exhaustive vulnerability guarantees.

## F. Documentation

Current README, architecture/scaling, threat model, known limitations, Windows guidance and release audit now agree. release_claims_matrix.md distinguishes playback/computational replay, scripted/arbitrary LLM continuation, tamper evidence/authenticity, virtual tools/host code, default/allowed capture, best-effort redaction, cooperative deadlines, configured ports and tested platforms. CHANGELOG and supplied third-party notices are included; MIT SPDX metadata and both license files are carried into built wheels.

E2/F1 historical stalls remain unattributed and were not reproduced in later bounded testing; not called fixed. F2's corrected redaction regression remains. Detailed diagnostics are optional and prior ~1.95x sample overhead is disclosed. No defect-free, universal-agent, enterprise, novelty or market claim. LangGraph checkpointing/branching is acknowledged.

## G. Release contents

Selected source includes Python/SDK/API/runtime, frontend source+lockfile+compiled assets, all original and targeted product tests, synthetic fixtures, setup/CLI guides, current benchmark CSV/JSON, eight genuine screenshots, MIT/third-party notices, changelog, architecture/privacy/retention/limits/replay docs and this report. No venv,npm modules,caches,DBs,private logs,raw stacks or historical Git bundle. A CANDIDATE_MANIFEST.json hashes every other included source file; external integrity JSON supplies the archive hash and final commit without self-reference.

Release filenames: GhostFrame_v0.1.0-rc.1_Source.zip and GhostFrame_M9-RC_integrity.json. Their verified absolute locations, SHA256, final commit and local annotated tag are supplied in the external handoff. Reproduce privacy with `python scripts/release_scan.py SOURCE_OR_ZIP --output ../scan.json`; normal tests/build/demo commands are in README. Package extraction/install and license metadata are checked after final assembly.

## H. Git status

Branch release/m9-rc-hardening in a separate local clone; original audited repository remains clean at 3ced8e87cbe7555f2bcda9ce28877aaa146664b1. Original preview tag preserved; no history rewrite/force push. Final commit and local annotated v0.1.0-rc.1 are recorded in external release-state manifest only after gates pass. No stable v0.1.0 tag, public push, deployment or publication.

## I. Residual issues

P0/P1:none confirmed unresolved within scope. Four product P2s:resolved for proposed distribution. Accepted historical P2 E2/F1 uncertainty, cooperative blocking/logical quotas/no secure erase/explicit unknown-secret limits and optional diagnostic overhead remain documented. Original environment pip advisory is historical; clean bootstrap patched. P3:upstream deprecation and CI actions still referenced by major tags, with explicit contents:read permissions added. One-platform/same-assistant and no human/commercial validation remain limits, not invented new blockers.

## J. Final release decision

**READY_FOR_OWNER_PUBLICATION_APPROVAL** for the selected sanitized source candidate and its declared local-first scope. This is not authorization to publish the historical Git repository or any artifact automatically.

## K. Next action

Owner reviews and authorizes publication of this specific source candidate. No further broad engineering/audit milestone is required by the demonstrated gates. Nothing will be publicly published without that separate instruction.
