# AMD open-firmware research and build tooling

LibreAMD is the working name for this independent AMD open-firmware research and build project owned by Noah Weinberger. The Python package provides an evidence-backed target catalog, offline survey and firmware-package inspection, and pinned coreboot recipes for exact boards. It does not claim that one image works on every AMD system or that a successful build will boot on a machine. The project is not affiliated with AMD, coreboot, Libreboot, or any board vendor.

| Coverage | Observed state |
| --- | --- |
| Catalog | 65 versioned target and research records; entries have distinct evidence and readiness levels. |
| Exact-board build recipes | 2: PC Engines APU2 and Star Labs StarBook Mk VI AMD. Local ROM builds and static checks are recorded in the [handoff](PROJECT_HANDOFF.md). |
| Generic virtual smoke | 1 i440fx QEMU path with a serial marker and controlled exit; separate from the AMD recipes. |
| Physical hardware validation | 0 project tests; Momiji remains survey-only. |

## What the software does

- `amd-fw catalog` validates, lists, shows, and exports versioned target and evidence records. CPU, SoC, board, recipe, build, and hardware results are separate claims.
- `amd-fw survey` imports an existing directory, tar archive, or ZIP archive without running collection commands. It writes a private normalized report and can preview a limited public case-study export.
- `amd-fw firmware inspect` hashes a supplied package and recognizes a small set of outer formats. It does not execute an installer, verify a signature, or establish that a package is a complete restoration image.
- `amd-fw sources fetch` explicitly acquires pinned upstream sources after an operator reviews restricted-input terms. `sources verify`, `build`, `reproduce`, and `artifacts` use local inputs and record build or comparison evidence. The build adapter checks exact host executable versions against a bundled lock.
- `amd-fw report TARGET` shows the catalog record, its recipe if present, and cited evidence together.
- An optional [generic i440fx QEMU smoke test](docs/research/generic-qemu-smoke.md) checks a separate virtual firmware path. Its result is not AMD board validation.

The catalog currently includes two exact-board recipes, `pcengines-apu2` and `starlabs-starbook-cezanne`, at the pinned coreboot 26.06 commit recorded in each recipe. Their binary dependencies have separate license conditions. Build manifests inventory selected source trees and required binaries; per-file coverage is incomplete. The Cezanne build may include additional PSP files referenced by pinned upstream configuration without an individual manifest hash for each file. Recipe presence and catalog status do not establish that either board was physically tested. The [build validation ledger](docs/build-validation.json) records final recipe and artifact hashes; [PROJECT_HANDOFF.md](PROJECT_HANDOFF.md) records current build, reproducibility, CI, and delivery results.

## Safe offline quickstart

Start in the repository root with Python 3.11 or newer. These commands use Fish and create only a project-local Python environment. The first install may contact the configured Python package index.

```fish
python3 -m venv .venv
source .venv/bin/activate.fish
python -m pip install -e .
amd-fw --json doctor
amd-fw catalog validate
amd-fw catalog show pcengines-apu2
amd-fw --json report pcengines-apu2
python -m unittest discover -s tests
```

`doctor` reports development tools. It does not probe firmware hardware. The catalog and report commands are offline and do not require an AMD motherboard. The [runbook](RUNBOOK.md) includes a copy-paste synthetic survey example, all source and build procedures, failure recovery, and privacy steps.

## Support and safety boundary

Only an exact upstream board target with a reviewed recipe can be selected for a build. A processor name, CPUID, SoC source directory, or similar retail model name cannot substitute for board-specific evidence. Builds run from pinned inputs in a network-isolated workspace when the locked host tools and required facilities are available. Generated ROMs are development artifacts. Artifact verification checks recorded bytes and selected structure; boot behavior and safety remain untested.

No normal command flashes firmware, reads a physical SPI chip, probes EC or SMBus hardware, changes TPM or Secure Boot state, or bypasses platform protections. Momiji is a private survey case and is excluded from physical experimentation. Raw surveys, vendor packages, upstream checkouts, and generated images belong outside Git. A public case-study export requires inspection of its allowlisted fields and publication rights before it is shared.

## Project documents

- [RUNBOOK.md](RUNBOOK.md): Fish-compatible operator procedures A through P.
- [PROJECT_HANDOFF.md](PROJECT_HANDOFF.md): observed state, validation, blockers, and next commands.
- [Support and validation policy](docs/support-policy.md): precise status meanings.
- [Architecture](docs/architecture.md), [evidence policy](docs/evidence-policy.md), [licensing](docs/licensing.md), and [privacy](docs/privacy.md).
- [Contributing](CONTRIBUTING.md), [security reporting](SECURITY.md), [license](LICENSE), and [notices](NOTICE).

## Project announcement

Maple Nekokami posted a [six-part Bluesky thread](https://bsky.app/profile/maple-nekokami.bsky.social/post/3mw5aev5nxl2e) about the verified build scope, the offline workbench, and the no-hardware boundary.

## Exit status

`amd-fw` returns `0` on success, `2` for invalid or rejected input, `3` for an unknown target, `4` for missing dependencies or inputs, `5` for integrity or schema failures, and `6` for other operational failures. The `--json` option belongs before the command name. Error text goes to standard error except rejected or failed structured operations requested with `--json`.
