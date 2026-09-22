# Contributing

Read `AGENTS.md`, `docs/support-policy.md`, and `docs/evidence-policy.md`
before changing target data or recipes. Use a feature branch. Run the
catalog validator and unit tests before proposing a change.

For a processor or SoC record, supply identity evidence, aliases, CPUID data
only where verified, and links to exact upstream source locations. For a
board, add the upstream mainboard path and symbol, revision constraints, and
dependency evidence. A recipe requires source locks, a reviewed configuration,
input hash policy, expected artifacts, and a real build attempt. An importer
or inspector change needs bounded synthetic fixtures and failure tests. Keep
private survey data and vendor binaries out of tests and Git.

Document a failed or blocked build as such. Do not replace an input with bytes
from another board to make a build pass. Prefer sending broadly useful board
and SoC fixes upstream to coreboot or the relevant project.
