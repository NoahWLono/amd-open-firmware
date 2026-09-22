# Support and validation policy

The catalog describes evidence, not a promise that firmware can replace a
machine's installed firmware. A processor record, SoC implementation, board
port, build recipe, successful build, emulator result, and hardware result are
distinct. Architecture `x86_64` includes processors from several vendors; it
does not mean a processor was made by AMD.

## Build readiness

`cataloged` means the identity has a primary-source reference. `research-only`
means there is no exact board recipe. `upstream-target-identified` means a
specific mainboard target is present at a pinned upstream revision.
`recipe-implemented` means this project has a validated recipe for that target.
`inputs-missing` means a named required input is unavailable or unverified.
`build-failed` and `build-verified` describe a particular attempted build and
environment, not all future builds. `emulator-tested` needs an observed guest
success signal. `externally-hardware-tested` needs attributable outside
evidence for an exact board revision and artifact. `project-hardware-tested`
needs a separately authorized project test. These are independent fields or
events; a later failure does not erase an earlier result.

Board revisions are explicit. An unknown revision is not silently equivalent
to a known revision. Retail product names and CPU families alone cannot select
a recipe. Recheck upstream target, dependency, and security information when
updating a pinned source revision. A stale reference remains visible with its
retrieval date and cannot be promoted to current build support without review.

## Openness and security

Each dependency may be free source, restrictive source, redistributable binary,
user-supplied binary, unresolved binary, immutable hardware code, not
applicable, or unknown. Availability on a public server does not grant
redistribution rights. A signed component is not cryptographically verified
unless the correct procedure and trust material were used. Reproducibility
does not prove that a build is safe, fully open, or compatible with a board.

No hardware validation is performed by the current project. Momiji remains a
survey-only case, never a build alias for another board.
