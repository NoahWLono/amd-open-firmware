# ADR 0005: Readiness claims and publication gates

Date: 2026-09-22
Status: accepted for the initial implementation
Owner: Noah Weinberger

## Decision

Catalog coverage, build recipes, successful builds, reproducibility,
emulation, external hardware reports, and project hardware tests are separate
facts. Claims carry primary source references or a particular local test
event. The catalog validator rejects a build claim without an exact pinned
mainboard. The CLI refuses to build a research-only case.

Raw survey files and their imported private reports remain outside Git. A
public survey export contains a fixed allowlist of normalized technical
fields and requires an explicit review flag for writing. Reviewers must still
inspect the resulting file and its publication rights. The normal workflow
does not publish ROM images or private evidence.

## Consequences

An image passing a compiler and static structure check is a development
artifact. A generic QEMU smoke test exercises only its named virtual path.
Neither result proves boot or safety on a physical AMD board. Release assets
require a fresh license, privacy, provenance, security, and exact hardware
validation review. Publishing a Git repository does not authorize publishing
firmware images or raw survey archives.

`docs/support-policy.md`, `docs/evidence-policy.md`, and `docs/privacy.md`
define the terms and reviewer duties in more detail.
