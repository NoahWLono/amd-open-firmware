# ADR 0001: Project architecture and boundaries

Date: 2026-09-22
Status: accepted for the initial implementation
Owner: Noah Weinberger

## Decision

LibreAMD is an independent Python tooling project. The repository slug is
`amd-open-firmware`, because that describes the work without implying a
particular board is supported. It does not copy or relicense coreboot,
openSIL, payloads, or vendor firmware. Board recipes pin and verify upstream
source revisions. The project builds only exact, reviewed upstream mainboard
targets. The catalog also records research-only platforms and survey cases.

A GitHub public-repository search for the exact name `LibreAMD` on 2026-09-22
returned no exact repository match. That limited search is neither a legal nor
a trademark clearance. `LibreAMD` remains a working name, while the neutral
repository slug avoids relying on the name for distribution.

Five modules have distinct trust boundaries:

1. `catalog` reads versioned project data and checks evidence links and build
   claims. It performs no network or host probing.
2. `offline` reads untrusted archives and firmware files with size and format
   limits. It never runs embedded commands or vendor installers. Private
   reports stay in a user-selected workspace outside Git.
3. `building` fetches pinned source on an explicit networked command, then
   verifies and builds in an isolated workspace. The build command does not
   fetch silently or access physical firmware devices.
4. `workspace` permits cleanup of one marked target build directory while
   leaving shared sources and private surveys intact.
5. `cli` applies stable exit codes and renders human-readable or JSON output.

The default workflow is catalog validation, synthetic offline import, source
verification, isolated build, artifact verification, and reporting. It does
not include a flasher. Momiji is a survey-only research case. No operation in
this project accesses its hardware.

## Evidence and status

Processor identity, silicon initialization, upstream SoC code, exact board
port, build recipe, successful build, emulator test, and physical test are
separate claims. The catalog stores evidence references and exact upstream
revisions. Build and test results are events tied to artifacts. A successful
compiler invocation does not alter hardware validation status.

## Distribution and privacy

Original Python tooling is licensed under Apache-2.0. Upstream source and
binary inputs retain their own licenses. A public download is not permission
to redistribute a binary. Raw surveys, source checkouts, binary inputs,
builds, and logs are excluded from Git. Public survey exports contain only
allowlisted normalized fields and require an explicit review flag.

## Rejected choices

- Generating board ports from CPU names would invent hardware topology.
- Vendoring a large coreboot mirror would obscure upstream provenance.
- Calling a QEMU smoke test an AMD hardware test would overstate evidence.
- Bundling an automatic flasher would cross the project's no-hardware boundary.
