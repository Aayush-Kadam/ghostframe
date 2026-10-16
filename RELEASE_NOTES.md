# GhostFrame v0.1.0-rc.2 — unpublished candidate

This candidate includes the cross-platform diagnostic stack normalization and
Windows API guard fixes already on main, plus the reviewer documentation from
PR #2. It keeps the same supported deterministic document driver and local-first
capture/evidence design. Python package version: `0.1.0rc2`; frontend version:
`0.1.0-rc.2`.

## Changes from the published rc.1

- Normalize stack path separators before exact module allowlisting. Directory
  prefixes stay private, unknown/lookalike modules reject and the frame cap remains.
- Expose Windows-only APIs to cross-platform type checking.
- Complete the core OS/Python matrix after individual failures.
- Add clear source/release and replay/evidence boundaries.
- Include documentation, frontend source and verification scripts in the source
  distribution as well as the separately prepared full source ZIP.

The original release notes and candidate manifest are preserved under
`docs/releases/v0.1.0-rc.1*` as historical evidence. They do not describe rc.2.
The rc.2 artifact manifest and its hashes are generated after the final source
commit, outside self-referential Git content.

## Qualification and limits

Use the M1-R verification report for candidate-specific installation, tests,
package metadata and CI results. Existing main/PR CI results are evidence for
those exact revisions, not automatic qualification of a new version label.

The API remains unauthenticated and trusted-local. Default capture is
metadata-only; explicit allowlists and redaction are bounded. Generic decorated
functions are playback-only. Hash-chain consistency is not authenticity.
Historical E2/F1 stalls remain unattributed. No additional agent/model coverage,
scientific result, third-party validation or defect-free guarantee is added.

MIT licensing and compiled frontend notices remain unchanged. This preparation
creates no tag or GitHub release. Publication requires explicit owner approval.
