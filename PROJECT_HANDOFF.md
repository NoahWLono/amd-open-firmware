# Project handoff

Updated: 2026-09-22
Owner: Noah Weinberger

## Purpose and boundary

LibreAMD is an independent AMD firmware research, catalog, offline inspection,
and exact-board build project. It is not a universal firmware image. No
physical firmware, SPI, EC, TPM, or platform-security device was accessed or
modified. Momiji remains a survey-only case and is excluded from physical
experimentation. This session used a development host, public pinned upstream
sources, and one owner-supplied archive imported offline.

## Repository state

- Checkout: `/home/noah/Documents/ChatGPT/MAPLEBOOT`.
- Private GitHub repository: [NoahWLono/amd-open-firmware](https://github.com/NoahWLono/amd-open-firmware).
- Branch: `codex/amd-open-firmware`.
- Validated source commit: `ef70dd163e6cf0ff3ee671431987cc31c5c4ec37`,
  pushed to the branch and confirmed by `git ls-remote`. The Node.js 24 CI
  update was verified on `391d6bc6996e907739916c24bb157fdb9b934ec3`.
  The delivery handoff was verified on `f84c5e187f7886a0643af57acc53902af1934165`.
  Resolve the current document commit with `git rev-parse HEAD`; this file
  cannot contain its own commit hash.
- Progress ledger: [docs/progress.json](docs/progress.json). Source evidence
  ledger: `src/amd_fw/data/evidence.json`. Observed build results are in
  [docs/build-validation.json](docs/build-validation.json).

## Implemented capabilities and coverage

- Installable Python package and `amd-fw` CLI for catalog inspection, bounded
  survey import, private reports, review-gated allowlist export, offline
  firmware inspection, pinned source fetch and verify, isolated exact-board
  builds, artifact inspection and verification, repeatability comparison, and
  marked build-directory cleanup.
- Catalog of 65 target and research records with 62 evidence records. Its
  processor and SoC records are not board support claims.
- Two actual coreboot 26.06 AMD board recipes: PC Engines APU2 (Puma,
  AMD GX-412TC) and Star Labs StarBook Mk VI AMD (Cezanne, Ryzen 7 5800U).
  Both produced ROMs via the project adapter and passed its static artifact
  checks. Their exact physical board revisions and boot behavior are untested.
- Generic coreboot i440fx QEMU payload smoke test passed with a serial marker
  and controlled exit. It exercises a separate virtual path, not either AMD
  board image.
- Source-only CI workflow, 81 passing local unit and integration tests, Fish A-P
  operator runbook, architecture and licensing decisions, and privacy policy.

## Source locks and local build results

The recipes pin coreboot 26.06 commit
`5cbf8afc4c08949c9b4ee1cb9dc5439add8a937e`, SeaBIOS commit
`b52ca86e094d19b58e2304417787e96b940e39c6`, exact submodule commits,
required file hashes, board symbols, and CBFS expectations. The bundled
`arch-linux-host-2026-09-22` executable lock is enforced. It does not freeze
all host libraries or the kernel. The builds ran in rootless Bubblewrap with
the network namespace unshared, no physical-device passthrough, and bounded
jobs and timeout. The build cleans disposable copied checkouts before compiling.

| Target | ROM SHA-256 | Size | Observed result |
| --- | --- | --- | --- |
| `pcengines-apu2` | `519ec13807fc3e514d158c9c4fffd080e2a1454890d477a8f4f083a8856dbef5` | 8 MiB | Two independent clean builds under the final recipe produced byte-identical ROMs; both artifacts verified. |
| `starlabs-starbook-cezanne` | `34164afa45c83eb46bf1107388f9a4679ae0c22ac11d42630bd3d2b8da9b9b3b` | 16 MiB | Two independent clean builds under the final recipe produced byte-identical ROMs; both artifacts verified. |

The APU2 final-recipe runs were compared directly byte for byte, and the
comparison report is preserved privately. The StarBook final two-build CLI
report is `reproducible` on this host. The public validation ledger records
both final recipe hashes, all four manifest hashes, ROM hashes, and scope. These
results do not establish boot, security, cross-host reproducibility, or
suitability for a physical board. No release image is eligible for publication
without the binary license review.

The generic QEMU ROM SHA-256 is
`544bde9eec85b4e7d1d36add97bd4d3a68d3bfa7661bbbe0c00e0087bd440b58`.
The latest preserved smoke result saw its serial success marker and expected
QEMU exit code 33. No AMD silicon-initialization conclusion follows from it.

## Tests and delivery state

The final integrated local suite passed 81 tests. Ruff format and lint checks,
Python compile checks, and catalog validation passed; the catalog has 65
targets and 62 evidence records. A source wheel built and installed in a fresh
offline venv, and its installed `amd-fw catalog validate` command passed.
All 19 Fish runbook code blocks passed `fish -n`. Both pinned source sets and
the host toolchain lock verified. The final staged audit passed. The private
GitHub push was verified. [Source checks run 35789774058](https://github.com/NoahWLono/amd-open-firmware/actions/runs/35789774058)
passed on commit `ef70dd1`, including format, lint, tests, catalog validation,
and staged-content audit. GitHub emitted a warning that the original action
pins target deprecated Node.js 20. The workflow now pins official Node.js 24
versions of checkout and setup-python. [Run 35789999557](https://github.com/NoahWLono/amd-open-firmware/actions/runs/35789999557)
passed on commit `391d6bc`, including install, format, lint, tests, catalog
validation, and staged-content audit.
[Run 35790235207](https://github.com/NoahWLono/amd-open-firmware/actions/runs/35790235207)
also passed on the delivery handoff commit `f84c5e1`.

## Announcement

Maple Nekokami posted a [six-part Bluesky thread](https://bsky.app/profile/maple-nekokami.bsky.social/post/3mw5aev5nxl2e)
about the project. All six posts, their reply chain, the owner's mention, and
the repository link were read back and verified through the account's public
records. The GitHub README links that thread. Account credentials were not
written to this repository or the private evidence directory.

## Private evidence and publication boundary

A restricted sibling directory, `MAPLEBOOT-private`, contains the owner-supplied
Momiji archive, its private normalized survey report, and preserved build
evidence. The public catalog's HP case includes only public vendor product
options and withholds archive-derived observations. No owner-reviewed public
export of the archive was published. The pinned build source cache was copied
to the private sibling directory, and both target source checks passed from
that copied location. Raw surveys, source checkouts, binary inputs,
build logs, ROMs, and comparison reports are intentionally excluded from Git.
The private build-evidence directory preserves the final StarBook run manifests,
ROMs, logs, and report, the APU2 runs and comparison report, and the generic
QEMU ROM and smoke result. A comparison report may refer to its original
`/tmp` run paths; the matching run IDs are preserved in the sibling directory.

Manifest component lists are curated. In particular, more Cezanne PSP files
may be incorporated from pinned upstream configuration than have individual
manifest hashes. The Star Labs `ec.bin` binary has MIT terms at the pinned
upstream blob commit, while the required AMD binary terms still block any
whole-ROM release decision. No private archive value, digest, or generated
firmware image belongs in the Git repository.

## Known gaps and next engineering steps

1. Complete a per-file component inventory and distribution-rights review
   before considering generated ROMs as release assets. The host toolchain
   lock is not a fully hermetic build environment.
2. Add an explicit verified staging path before a future recipe can use a
   separately supplied binary. Manually adding untracked files to the source
   cache is not a reliable build input method.
3. For any future hardware work on a different board, obtain separate
   action-specific authorization and an independently established recovery
   process. Momiji remains excluded. For the private Momiji case, an owner
   review is required before any allowlisted public case export.
4. The owner requested ASCII Maple Nekokami catgirl art for a future UEFI page
   only after the project is fully operational. No UEFI page or physical boot
   has been implemented, so this remains deferred.

## Exact resume commands

From the checkout in Fish:

```fish
source .venv/bin/activate.fish
git status --short --branch
git rev-parse HEAD
amd-fw catalog validate
python -m unittest discover -s tests -v
ruff format --check src tests tools
ruff check src tests tools
python tools/check_staged.py
```

Use [RUNBOOK.md](RUNBOOK.md) for source acquisition, builds, comparison,
privacy review, release checks, and cleanup. Use the private sibling evidence
directory to inspect recorded run manifests. The exact build target is never
inferred from a CPU or retail product name.
