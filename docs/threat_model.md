# Security assessment

Trust the single local owner who installs/runs Python code. Ticket text, tool observations, replacement JSON and event payloads are untrusted data. The supported document dispatcher manipulates a deep-copied virtual dictionary under /documents; it has no host shell or filesystem adapter. SDK decorators observe caller-owned code and provide no containment for it.

SQLite short transactions, foreign keys, sequence constraints, no-update/delete triggers, domain-separated hashes and checkpoint ownership checks detect inconsistencies. A privileged database administrator can replace a complete consistent history; there is no signature, external anchor or authenticity proof.

New SDK metadata-only capture omits names, project labels, payloads, custom metadata and exception messages before persistence. Explicit tool/scalar-field allowlists and known-key/value redaction operate at the Store boundary. Explicitly allowed unknown secrets can still leak; old traces are not retroactively sanitized. No encryption-at-rest or secure erase is promised.

New-run retention is 30 days after finalization unless disabled/pinned. Cleanup protects retained descendant ancestors and active operation leases, and rolls back on interruption. Logical byte/count quotas, streamed request and buffered response caps are enforced. Deadlines/cancellation are cooperative around controlled transitions; arbitrary SDK functions and blocked OS calls are not forcibly interrupted.

The packaged CLI binds only 127.0.0.1. Browser Origin must exactly match a validated loopback Host and the actual bound port; other ports, remote origins, malformed authorities and lookalike hosts reject. A fixed local Vite origin on 5173 is trusted only through explicit development opt-in. No wildcard CORS or credentials policy is added. An absent Origin is allowed for trusted local non-browser clients. Host names must be exact loopback names, protecting against ordinary DNS-rebinding through an attacker-owned name; these checks are not authentication or isolation against other local software. Do not expose the service publicly.

JSON schemas, ingress/egress budgets and CSP keep payload text inert. No pickle, eval or event-code execution adapter exists. Storage/OS failure can leave incomplete evidence; no fake completion is inferred. Optional diagnostics use bundled synthetic fixtures, bounded observers and function-only stack sampling. Raw captures can contain local paths and stay private.

Historical E2/F1 stalls remain unattributed; later finite runs did not reproduce them. F2's redaction complexity correction remains tested. No human security certification, enterprise multi-tenancy, guaranteed future reliability or exhaustive vulnerability audit is claimed. See privacy_policy.md, retention_policy.md, resource_limits.md and release_claims_matrix.md for current contracts. Earlier milestone documents are historical records, not current guarantees.
