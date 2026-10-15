> Historical assessment: use release_claims_matrix.md and milestones/M9-RC.md for current scope/results.

# Evaluation protocol

Fixture expectations are authored in `scripts/build_fixtures.py` before executing the driver. They specify exact final files, expected error category, task correctness and permitted branch outcomes. `tests/test_runtime.py` uses these expectations rather than copying results into oracles.

Thirty development scenarios cover file decisions, tool observations, retries, checkpoint/branch behavior, policy/approval and hostile data. Ten additional regression cases are a separate manifest set. They are not called an externally sealed holdout. SDK tests separately cover actual unsupported Python serialization, nested spans, async concurrency and process death.

Benchmark: one declared warm-up, then three repeats of every scenario. Report 90 development attempts and 30 regression attempts separately; none excluded. Each replay reruns the driver. Every eligible branch attempt, including failure, remains in its denominator. State accounting independently applies persisted mutation records to starting virtual files and compares final files. All raw trials are emitted as CSV.

Unrecorded baseline executes the same driver/tools without SQLite events; stored-playback baseline retrieves events only. These do not establish comparative performance against commercial tools. Report median and nearest-rank sample p95 with sample counts. Small-fixture timings are not production throughput estimates. Browser large-trace timing is a single sample.

Integrity injection and fault handling are measured by tests, not folded into fabricated benchmark percentages. Coverage includes all Python package modules, including CLI/benchmark. The core runtime, ledger and sandbox exceed the 85% target at final verification. No LLM judge is used.

## M8-R2 reliability protocol

The eligible set remains fixture version 1: 30 development + 10 regression cases, three trials each. All are declared successful-deterministic-replay expectations, including fixtures whose tool/task outcome is a controlled negative. `benchmarks/reports/M8-R2/expectations.json` records case IDs and fixture SHA256 before the sealed protocol. Resource-rejection tests are reported separately.

`scripts/m8r2_verify.py --mode batches --output <new-directory>` executes exactly three original 120-attempt batches and retains every batch. It does not retry until green or discard failures. A single declared warm-up remains excluded. Temporary DB directories are retained under the same Windows preview-comparison accommodation; real operation-lease cleanup still runs. Failure rows now record source-recording versus replay stage, elapsed failed-stage time, typed code and failed run ID.

`--mode affected` executes 20 trials per E2/F1/F2, ten fresh stores and ten warmed. These are separate from the original full-benchmark denominator. Sixteen-stage diagnostic timing is hierarchical and includes tracing overhead; it must not be interpreted as exclusive production latency. Final code fingerprint is checked against the measured source.

Historical 117/120 results remain preserved. Current 360/360 does not establish the root cause of historical non-reproduced stalls. See the M8-R2 report for the withheld root-cause gate and separate sandbox event-loop hang diagnosis.
