# Enforced resource budgets

Limits is configurable on Store/Recorder/create_app. Positive finite values are validated; byte/count fields must be integers. The defaults below describe accepted logical data, not an exact physical SQLite disk-size cap.

| Boundary | Default |
|---|---:|
| Event payload | 64 KiB |
| Any string / virtual file | 32 KiB |
| Nested JSON depth / visited nodes | 24 / 20000 |
| Events / checkpoints per run | 10000 / 256 |
| Checkpoint input | 1 MiB |
| Logical retained data per run / per store | 16 MiB / 256 MiB |
| Retained runs | 1000 |
| Controlled steps / execution time | 64 / 60 seconds |
| Active controlled operations per store | 4 |
| Retained intervention branches per source / ancestry depth | 100 / 1 |
| HTTP request body / response / export | 32 KiB / 32 MiB / 32 MiB |
| HTTP path or query / total headers / header count | 4096 characters or bytes / 16 KiB / 100 |
| Per-process active HTTP requests | 8 (2 times active_operations) |
| Run page / event page | 200 / 500 maximum |
| Virtual files / total file content | 100 / 1 MiB |

Ingress counts streamed chunks before extending a bounded buffer, including requests without Content-Length. Deep, cyclic, non-finite, binary and oversized payloads fail safely. Compressed request bodies and archive imports are unsupported and rejected; there is no decompression adapter. Request receipt has a finite 60-second total deadline. Egress is buffered within the response cap; it is not an unbounded streaming export. Queries check byte budgets before retrieving stored rows. React loads at most 10001 events including one reserved failure record and rejects empty continuation pages.

Logical byte counters are initialized from existing SQLite content once, then maintained in the same transactions as recording and cleanup. Independent tests reconcile counters to actual JSON byte lengths. SQLite indexes, WAL, free pages and table overhead are outside this logical budget; normal OS capacity failures remain possible. One bounded terminal failure event per run is reserved beyond the normal event/byte quota (at most 4096 bytes per run). Normal recording cannot use that reservation to append arbitrary data.

Quota errors do not truncate replay-critical state or report replay/branch success. Failed operations preserve source evidence. Timeouts and cancellation are cooperative checks around the bounded bundled driver/tool transitions; caller-owned arbitrary Python functions decorated by the SDK are not forcibly preempted. The Engine cancel event and HTTP disconnect propagate into controlled executions. A blocked OS call can delay recognition until the next check. Physical disk failure can prevent even a terminal write; such a run remains incomplete, never falsely successful.

All branches/replays use SQLite-backed active-operation leases. Admission, retained child-count and ancestry constraints are checked under locked transactions. Connections close on normal exit and exceptions, including Windows cleanup. Virtual mutations validate proposed file state before replacing the dictionary and appending a journal entry. No host filesystem mutation dispatcher is provided.
