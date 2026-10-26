# Semantic properties and timing evidence

Verify #10 failed Ruff I001 in scripts/reviewer_check.py; 310330c corrected
import ordering. Verify #11 (Windows 3.11) and #12 (Windows 3.12) failed
Hypothesis's five-second deadline in the SQLite recording/replay property.
The logs report 42.444 s and 31.562 s respectively, with 206 passing tests.
Hypothesis could not reproduce the timing failure consistently. The cause of
the pauses is unknown; these logs do not demonstrate a semantic product defect.

5fc99ec removed this property's per-example deadline, retained all 15 generated
examples and assertions, and capped core CI jobs at 20 minutes. Verify #13
passed all five jobs. That change remains on m3/independent-reproduction and
was copied to m3/reviewer-ready (Verify #15), but was absent from default main
at 4e8699c despite the green Verify #14. This patch carries the same semantic
repair to main for review. It neither fixes the unexplained pause nor promises
five-second latency. Performance measurements remain separate from correctness.

The workflow retains Ubuntu/Windows, Python 3.11/3.12, Ruff, mypy, frontend
contracts, production build and browser checks. Both job types have a 20-minute
bound, fail-fast remains false, and permissions remain contents: read.
Node-20 actions are replaced with exact official Node-24 release commits:
checkout v5.0.1, setup-python v6.1.0 and setup-node v5.0.0. Hosted runners
already satisfy their runner >=2.327.1 requirement. Application Node stays 22.
The Starlette/httpx deprecation warning is separate dependency maintenance;
this change does not suppress it or alter the runtime dependency contract.

Historical runs remain in Actions and notifications after repairs. Green CI
is evidence for that exact commit and coverage, not a guarantee of no defects.
