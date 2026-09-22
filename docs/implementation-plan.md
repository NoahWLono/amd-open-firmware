# Initial implementation plan

The binding requirements are the owner-provided master project prompt. The
work is split into independently testable components. This plan records the
interfaces used in the first engineering pass; later evidence may narrow
target coverage without weakening the required proof for a claim.

1. **Catalog foundation.** Test schema/version rejection, evidence references,
   exact-board build claims, list/show/export, and offline CLI exit codes.
   Implement `src/amd_fw/catalog.py`, `src/amd_fw/cli.py`, package metadata,
   and synthetic test data. Verify with `python -m unittest discover -s tests`.
2. **Offline workbench.** Test safe archive enumeration, failed-command
   classification, manifest defects, allowlist export, and bounded opaque
   firmware inspection. Implement `src/amd_fw/offline.py` and CLI wiring.
3. **Source and build adapter.** Pin an actual upstream AMD mainboard and
   source revision. Test recipe validation, source lock, offline build
   refusal when inputs are missing, artifact manifests, and reproduction
   results. Exercise a real target where dependencies permit.
4. **Evidence and docs.** Record primary source locations, retrieval dates,
   confidence limits, verified targets, licensing, architecture, runbook,
   security policy, contribution path, and handoff. Validate documented
   commands against the installed CLI.
5. **Audit and delivery.** Run tests, inspect staged paths and possible
   private data, commit in milestones, create a private repository in the
   authenticated account, push, and verify the remote state and CI result.

Project-wide constraints: no physical hardware access, no flashing, no
platform-security changes, no invented support, no private archive in Git,
Fish-compatible operator commands, no em dashes in original documentation,
and no automatic network access in offline commands.

Review focus: hostile archive paths and links; truncated or oversized
firmware inputs; catalog claims lacking exact board evidence; interrupted
source/build workspaces; private identifiers in staged content.
