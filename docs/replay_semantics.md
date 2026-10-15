# Replay and fork contract

Playback does not call `DocumentDriver`, `Sandbox.call`, a model or an external API.

Offline replay does call `DocumentDriver.action` and `observe`. At each action it checks the expected tool signature. Read-ticket and approval observations come from persisted completion/error records; virtual mutation and list tools execute against an isolated copy. Every agent state, action, tool result, failure, denial, side effect and final outcome enters the semantic comparison. IDs, wall-clock timestamps, durations, hash metadata and fresh checkpoint identifiers are excluded. A semantic mismatch is detected before successful run finalization. Failed runtime records use RUN_FAILED/DIVERGED and return a typed error with the earliest detected mismatch and failed run ID.

Only a successful `read_ticket` response can be replaced. The fork validates Ticket and virtual path constraints, restores that response's pre-call checkpoint, records one intervention and invokes the same downstream driver. Subsequent tools execute freshly in the virtual sandbox. No downstream source observations are reused. Shared prefix ancestry is explicitly referenced, not copied and relabeled as executed.

The original evidence digest must remain equal before and after fork. A no-op replacement can produce unchanged actions/state and is displayed as such. Alignments use exact tool signatures and sequence-aware matching; uncertain replacements are sequence-only. First observed divergence is an observation about this experiment, not proof of uniquely established cause.

Arbitrary SDK functions, unknown driver versions, incomplete/redacted captures, branch-of-branch and branch replay fail closed. Neural-model continuation is not implemented. The logical step cap is 64, not a general wall-clock timeout for arbitrary SDK functions.


## M8-R update

See [privacy policy](privacy_policy.md), [retention lifecycle](retention_policy.md), [enforced resource budgets](resource_limits.md), and [security self-review](security_review_M8-R.md). These define the hardened behavior and supersede preview statements about missing capture allowlists, retention and resource bounds. Historical milestone reports remain historical evidence.
