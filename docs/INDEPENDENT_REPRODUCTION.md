# Independently evaluate GhostFrame

For Python developers debugging a bounded deterministic document-agent workflow: connect recorded actions, virtual state and a changed-observation continuation in one local evidence trail.

The checker records a virtual deletion incident, replays it, changes one tool observation, recomputes a branch, validates an export and deliberately corrupts it. Expected: REPLAY_SUCCESS, BRANCH_SUCCESS, original_correct=false, branch_correct=true, valid_export=true and tamper_rejection=BUNDLE_CORRUPT. IDs, digests, timings and temp paths may differ; these semantic outcomes must not. The API is trusted-local; generic SDK functions are playback-only. This is not live-model replay, arbitrary agent resumption or signed authenticity.

## Source, installation and five-minute check

This M3 branch is a reviewer preparation branch based on 40badbe4300e7fd71f5d02af8db572bc6b806451; it is not integrated main or a new published release. Record its actual HEAD with `git rev-parse HEAD`. Use the exact commit listed in the delivered package manifest; do not silently substitute latest main.

Windows and Ubuntu Python 3.11/3.12 are covered by existing project CI; macOS is not freshly qualified. Use Python 3.12 for this procedure. Git and initial package-registry network access are required; no API key, paid service or Docker is required. Resource estimate, not measurement: 2 GB free RAM, 1 GB free disk; allow additional space for optional development dependencies. Five minutes is a target after dependencies are installed, not a measured cold-network guarantee.

```powershell
git clone https://github.com/Aayush-Kadam/ghostframe.git
cd ghostframe
git checkout m3/independent-reproduction
py -3.12 -m venv .venv
.venv/Scripts/python.exe -m pip install -e \".[dev]\"
.venv/Scripts/python.exe scripts/reviewer_check.py
.venv/Scripts/python.exe -m pytest -q
```

On Ubuntu, create with `python3.12 -m venv .venv` and replace `.venv/Scripts/python.exe` with `.venv/bin/python`. Commands run from the repository root. The reviewer script uses installed packages and synthetic data; it must exit zero only when both positive and negative expectations hold. Save stdout, stderr and the actual exit code. Also save `python -m pip freeze` and `git rev-parse HEAD`.

Dependencies use bounded ranges in pyproject.toml; requirements-runtime.txt records a narrower environment, not a universal lock. Compiled frontend assets ship in the source. Optional UI: `.venv/Scripts/python.exe -m ghostframe.cli serve`; keep it on loopback. Do not attach real traces to feedback.

## Troubleshooting and feedback

If Python is missing, install a supported Python from its official provider, then create an isolated environment. If imports fail, use the same interpreter for installation and the check; do not mix environments. Report solver-wheel/architecture failures instead of substituting another solver. On Windows, temporary-directory permission failures should be investigated under your normal account; do not disable endpoint protection. A failed negative test is a bug and must not be relabeled success. ID/hash differences alone are expected; semantic differences are not.

Open the repository's independent-reproduction issue template only when you choose to disclose the report publicly. Alternatively send the completed fields privately through an owner-agreed channel. Provide environment, install/test failures, negative outcomes, documentation friction, usefulness and missing features. Do not disclose reviewer identity or communications without consent. Author-run checks are labeled self-tests and never populate the independent evidence ledger.
