# A reviewer entry to GhostFrame

GhostFrame is a small local debugging system for a supported synthetic document
agent. Its distinctive engineering is the connection between capture policy,
transactional evidence, deterministic replay, and recomputed virtual effects.

```text
Python SDK / document policy -> capture and redaction -> SQLite evidence
                                                     -> playback
supported document checkpoint + replacement observation -> continuation
SQLite evidence -> loopback API -> React timeline / comparison
exported JSON -> offline consistency verifier
```

## Try the actual incident

Follow the root README installation and run `python -m ghostframe.cli demo`.
It prints generated IDs and structured outcomes. Expected semantic results:
`REPLAY_SUCCESS`, `BRANCH_SUCCESS`, original `task_correct: false`, branch
`task_correct: true`, and valid evidence chains. IDs and hashes vary by recording;
the example operates on virtual files.

Run `python -m ghostframe.cli serve` for the compiled interface. Keep the API on
loopback. Generic decorated functions are playback-only; the supported document
driver supplies the checkpoints and resumable policy.

## Verify what the result means

Run the root README's pytest, Ruff, and mypy commands. The portfolio audit on
16 October 2026 freshly ran 207 Python tests successfully on Windows/Python
3.12.14, with 85% statement coverage, plus Ruff and mypy on 15 source modules.
This is author-side engineering verification, not independent human validation.

The existing main CI run
[38748486727](https://github.com/Aayush-Kadam/ghostframe/actions/runs/38748486727)
passed four OS/Python core jobs and a separate web job. The published
`v0.1.0-rc.1` predates the cross-platform repair. A current-main pass does not
repair or requalify that historical artifact.

## Limits worth testing

- A consistent unsigned export does not establish authenticity.
- Redaction is bounded; explicit payload capture is not universal secret detection.
- Logical quotas do not cap physical SQLite/WAL bytes.
- Historical E2/F1 stalls remain unattributed.
- Branch execution is restricted to the implemented driver, not arbitrary agents.

See [architecture](architecture.md), [threat model](threat_model.md),
[replay semantics](replay_semantics.md), and [limitations](limitations.md).
