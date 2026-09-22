# Build provenance and reproducibility

A build report records the exact target, recipe revision, source commit,
submodule revisions, configuration, hashes for explicitly required inputs,
host executable versions, build isolation settings, command, output hash, and
static validation results. If a build
stops, its log and last successful stage remain available in the workspace.
The manifest excludes itself from its own checksum set.

The manifest has a curated component inventory with incomplete per-file coverage.
Pinned upstream `fw.cfg` can incorporate further Cezanne PSP files without
individual hashes in this manifest. The pinned source-tree commit and local
checkout establish the larger input set for a repeat build. A future release
review must account for every incorporated component and its rights.

Two independent clean builds are required for a bit-for-bit reproducibility
claim. A matching normalized report is useful only when labelled separately.
Different hashes remain a failed reproducibility result until the difference
is understood. Neither result proves a firmware image safe to flash.

Artifacts with unresolved input licensing or no hardware validation are
development artifacts. The normal project workflow does not publish hardware
images. See `RUNBOOK.md` for exact commands and workspace paths.
