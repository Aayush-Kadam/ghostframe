# Retention and lifecycle

New runs use RetentionPolicy(enabled=True, retention_days=30, cleanup_on_startup=True). Each run snapshots its retention opt-in and duration at creation. The expiry clock begins at RUN_COMPLETED or reserved RUN_FAILED finalization, including failed controlled executions. A later Store default cannot override a run's opt-out. Incomplete/abandoned runs do not expire automatically. No unsafe inference of abandonment is made.

New lifecycle metadata lives in separate SQLite tables; original event/checkpoint schemas and hashes remain. Historical runs without lifecycle entries are exempt from automatic deletion. Manually pinned runs are exempt. A retained or active descendant retains its ancestors. Cleanup deletes whole eligible dependency groups, leaves shared ancestors intact, and never removes host files. There are no separate blobs: all supported payloads and snapshots are SQLite JSON.

Automatic cleanup runs when a Store opens, including CLI operations except the retention inspection/manual commands. There is no periodic background scheduler. A long-running API needs a restart or an explicitly invoked cleanup to process later expiry. Retention status/dry-run do not automatically delete traces. Manual apply requires --yes after review:

    python -m ghostframe.cli --db .ghostframe/ghostframe.db retention status
    python -m ghostframe.cli --db .ghostframe/ghostframe.db retention dry-run
    python -m ghostframe.cli --db .ghostframe/ghostframe.db retention apply --yes

Dry-run lists run IDs and owned events/checkpoints/run/lifecycle rows. Cleanup operates in one BEGIN IMMEDIATE transaction. Delete triggers are dropped and restored inside that transaction; interruption, including abrupt process death, rolls back data and triggers. Byte accounting changes share that transaction. Cleanup creates an audit record; the latest 1000 cleanup batches are retained. Audit housekeeping does not delete user trace data. No database, unrelated directory or arbitrary filesystem path is removed.

SQLite-backed process leases protect active replay/branch sources across processes. Dead processes' leases are pruned using native read-only process checks; inaccessible or reused process identities are treated conservatively as live. A process that dies during recording leaves incomplete evidence, not a successful trace. Operators may need to investigate abandoned traces or conservative stale leases; automatic deletion is intentionally withheld.

Append-only means events and checkpoints cannot be changed/deleted during a retained run's lifecycle through supported APIs. Explicit expiry authorizes deletion of whole expired histories. Hashes detect accidental or unauthorized ledger changes within the tested boundary, not a database administrator rewriting evidence. Deletion is not cryptographic erasure: SQLite pages, backups and exported files can retain historical content.
