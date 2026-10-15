# M9-RC four-finding remediation

Original baseline and original M9 37/38 result remain unchanged in their preserved locations. No original Python case or frozen M9 expected outcome was deleted or weakened. The 38 cases include the eight E-group cases; they are not counted twice.

| Finding | Root cause | Correction | Retest / status |
|---|---|---|---|
| M9-001 configurable port | Fixed origin strings omitted nondefault bound origins | Exact loopback authority and actual bound-port validation, same-origin check; explicit fixed Vite opt-in; CLI port range validation | Original D04 and D05 pass on8879; default8765, assets/reads/writes/branch/reload and forbidden Host/Origin tests pass. RESOLVED |
| M9-002 contradictory docs | Preview paragraphs persisted beside superseding appendices | Current README/threat/architecture/limitations/setup/release docs reconciled; claims matrix maps evidence and caveats; historical reports remain historical | Reviewed current release-facing documents against actual controls and tests. RESOLVED |
| M9-003 local paths | Private forensic artifacts were mixed into a distribution handoff | Copied home, workspace and hostname prefixes sanitized; selected public source excludes logs/DBs/cache/history; original evidence preserved separately; genuine new screenshots | Source/ZIP scans, manifest and extraction verified. Historical Git still has identifiers, is not rewritten and is excluded. RESOLVED for proposed source distribution |
| M9-004 SDK workspace heading | UI assumed every run was the virtual driver | Actual driver/synthetic provenance and available final-state determine heading/tab/state; generic SDK tool events and missing snapshots explicit | Five frontend cases and14 actual-API browser assertions cover SDK, metadata-only, virtual, missing/partial state; branch comparison also passes. RESOLVED |

Focused commits:56a4420 port/origin;2e51236 UI;8cfaabd documentation;708fe39 targeted tests;67a7425 sanitation/selection;723a7b9 rebuilt assets;6c0500d reviewed screenshots/privacy. Later release-only commits add current measurements, metadata/notices and final manifests; the final commit/tag are recorded externally to avoid self-reference.

The frozen M9 runner and fixtures were copied byte-for-byte.36 runner cases plus original D04/D05 browser cases passed on the new implementation. The original custom-port reproducer did not gain a special allowlist entry or weaker expected behavior. Exact source/runner/frozen hashes and attribution are in release-summary.json and private verification records. Final clean-extraction tests cover the unchanged final implementation after lint-only spelling cleanup.

Original M9 Windows mypy block is historical. M9-RC's normal authorized Python module invocation with the project config passed15 modules. No security policy was disabled, untrusted bypass binary run or alternate OS result substituted. Initial lint issues and harness sanitation/path mistakes were corrected and retained in private logs; no product test failure was hidden.
