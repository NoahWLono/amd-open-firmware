# Operator runbook

This runbook is for a development host and the owner's authorized project checkout. Every command block uses Fish syntax. Run commands from the repository root after procedure A unless a procedure says otherwise. Commands that accept a sample path or target require the operator to set that value explicitly. Stop when a prerequisite or check fails; a later command in a block does not repair an earlier failure.

The default private workspace is `$HOME/.local/state/amd-fw`. Keep it outside this Git checkout and restrict access to its owner. The normal commands never require access to a physical motherboard. In particular, Momiji is a survey-only case: do not connect to it, probe it, flash it, or change its firmware or security state. No procedure here authorizes hardware experimentation. The source and build procedures are for exact reviewed board recipes, and their artifacts remain development artifacts.

Use [PROJECT_HANDOFF.md](PROJECT_HANDOFF.md) for the current branch, actual build and test outcomes, and unresolved blockers. The commands below describe operations; a command appearing here does not mean its outcome has been observed in this checkout.

## Command and workspace conventions

CLI options `--json`, `--workspace`, and `--catalog-dir` precede the command name. `--json` gives a machine-readable result, including an `error.code` and any available `log_path` when an operation fails. The CLI returns `0` for success, `2` for invalid or rejected input, `3` for an unknown target, `4` for missing tools or inputs, `5` for integrity or schema failure, and `6` for another operation failure. Human-mode errors go to standard error. Some offline inspection rejections use a JSON `status` of `rejected` with exit `2`.

The repository contains original source, tests, bundled catalog data, and recipes. The private workspace holds `surveys/`, `sources/`, and `builds/`. `sources/coreboot` is a pinned upstream checkout, `sources/fetch.log` records acquisition, and `sources/decisions/TARGET.json` records the operator's restricted-input decision. A build writes `builds/TARGET/RUN_ID/` with `build.log`, `cbfs.txt`, `manifest.json`, and `artifacts/coreboot.rom`. The manifest's component inventory covers selected pinned trees and required binaries; per-file coverage is incomplete. Keep all of these outside Git. `reproduce` adds a `builds/TARGET/reproduce-*.json` comparison report. Check the returned paths rather than guessing a run ID.

## A. Fresh development setup

**Purpose:** Install the Python CLI and check host tools in an isolated environment.

**Prerequisites:** An authorized source checkout, Fish, Python 3.11 or newer, Python `venv`, and enough disk space for the selected work. Git is needed for source acquisition. Building also needs coreboot's host prerequisites, including `make`, `gcc`, `ld`, `as`, `bison`, `flex`, `iasl`, and working `bubblewrap` user and network namespaces. The build adapter requires exact host executable versions in `src/amd_fw/data/toolchain-lock.json`; the current profile is `arch-linux-host-2026-09-22` and includes Python 3.14.7. Other Python 3.11+ hosts can use the catalog and offline inspectors but may be unable to build. `ruff` is optional for local linting. The package build backend is pinned to `setuptools==84.0.0`.

**Environment:** A development host, in the repository root. Python packages go into `.venv`; the initial package install may use the configured Python package index. Do not run this on Momiji.

**Inputs:** This source checkout and the configured package index, if `.venv` lacks the pinned build backend.

**Exact commands:**

```fish
pwd
test -f pyproject.toml
python3 --version
python3 -m venv .venv
source .venv/bin/activate.fish
python -m pip install -e .
amd-fw --json doctor
```

For the pinned local lint tool, run `python -m pip install -r requirements-build.txt` inside the activated environment. Do not install these Python packages globally.

**Expected outputs:** An `amd-fw` executable in `.venv/bin` and a JSON doctor report with tool paths and `hardware_access: not_performed`. `doctor` lists availability; it does not enforce the exact build toolchain lock.

**Success criteria:** `amd-fw --json doctor` exits `0`, and the reported Python version is at least 3.11. A missing optional tool in the doctor report does not prevent offline catalog use.

**Common failure modes:** Missing `venv`, an inaccessible Python package index, incompatible Python, or a build host that lacks one of the tools listed above.

**Recovery or cleanup:** Resolve the named host dependency, then repeat the failed command. Remove only the project-local `.venv` if reinstalling the environment. Do not clear a private workspace to fix installation.

**Privacy:** Installation needs no survey or firmware input. Review the package index used by `pip` if the host has a restricted network policy.

**Network required:** Possibly for the first Python install; `doctor` itself is offline.

**Physical hardware accessed:** No.

## B. First successful use with synthetic data

**Purpose:** Validate the bundled catalog and exercise the importer without private material or a supported board.

**Prerequisites:** Procedure A and a writable temporary directory.

**Environment:** The development host, in the repository root. The temporary directory is outside Git.

**Inputs:** A synthetic `board_name` file created below.

**Exact commands:**

```fish
umask 077
set -gx AMD_FW_DEMO (mktemp -d -t amd-fw-demo.XXXXXX)
mkdir "$AMD_FW_DEMO/survey"
mkdir "$AMD_FW_DEMO/survey/dmi"
printf 'SYNTH-BOARD\n' > "$AMD_FW_DEMO/survey/dmi/board_name"
amd-fw catalog validate
amd-fw --json catalog show pcengines-apu2
amd-fw --json --workspace "$AMD_FW_DEMO/state" survey import "$AMD_FW_DEMO/survey" > "$AMD_FW_DEMO/import.json"
set -gx AMD_FW_SURVEY_ID (python -c 'import json,sys; print(json.load(open(sys.argv[1]))["survey_id"])' "$AMD_FW_DEMO/import.json")
amd-fw --json --workspace "$AMD_FW_DEMO/state" survey report "$AMD_FW_SURVEY_ID" > "$AMD_FW_DEMO/report.json"
amd-fw --json --workspace "$AMD_FW_DEMO/state" survey public-export "$AMD_FW_SURVEY_ID" > "$AMD_FW_DEMO/preview.json"
python -c 'import json,sys; r=json.load(open(sys.argv[1])); assert r["technical_fields"]["board_name"] == "SYNTH-BOARD"; print("synthetic import verified")' "$AMD_FW_DEMO/report.json"
```

**Expected outputs:** A catalog validation count, a board record, `import.json` with a survey ID, a private `report.json`, and `preview.json` with `status: review_required`.

**Success criteria:** Every command exits `0` and the final assertion prints `synthetic import verified`. The case-study preview should contain only the synthetic technical field.

**Common failure modes:** Catalog schema errors, an uninstalled CLI, a read-only temporary directory, or an importer rejection.

**Recovery or cleanup:** Inspect the failed command's standard error. Retain the demo directory while diagnosing. Once finished, delete only the path printed by `printf '%s\n' "$AMD_FW_DEMO"` after confirming it begins with the intended temporary directory prefix.

**Privacy:** The fixture is synthetic, but the generated report uses the same private-report layout as a real import.

**Network required:** No.

**Physical hardware accessed:** No.

## C. Import an existing hardware survey

**Purpose:** Analyze a previously collected archive or directory and record collection gaps. Import does not rerun any survey command.

**Prerequisites:** Procedure A, local possession of a survey, and authority to process it. Keep the archive outside Git. Accepted sources are bounded regular directories, tar archives, and ZIP archives. Unsafe paths, links, special files, executable members, or excessive expansion are rejected. The importer caps a decompressed tar stream at 40 MiB, ZIP central-directory metadata at 2 MiB, and does not accept ZIP64.

**Environment:** The development host, offline, with a private workspace outside the repository.

**Inputs:** An exact path set as `AMD_FW_SURVEY_ARCHIVE`. Set it to the available local copy; a path from an earlier chat is not evidence that a file exists here.

**Exact commands:**

```fish
umask 077
set -gx AMD_FW_WORKSPACE "$HOME/.local/state/amd-fw"
set -gx AMD_FW_SURVEY_ARCHIVE "/absolute/path/to/existing-survey.tar.gz"
test -e "$AMD_FW_SURVEY_ARCHIVE"
mkdir -p "$AMD_FW_WORKSPACE/operator"
chmod 700 "$AMD_FW_WORKSPACE" "$AMD_FW_WORKSPACE/operator"
amd-fw --json --workspace "$AMD_FW_WORKSPACE" survey import "$AMD_FW_SURVEY_ARCHIVE" > "$AMD_FW_WORKSPACE/operator/import.json"
set -gx AMD_FW_SURVEY_ID (python -c 'import json,sys; print(json.load(open(sys.argv[1]))["survey_id"])' "$AMD_FW_WORKSPACE/operator/import.json")
amd-fw --json --workspace "$AMD_FW_WORKSPACE" survey report "$AMD_FW_SURVEY_ID" > "$AMD_FW_WORKSPACE/operator/report.json"
```

**Expected outputs:** A deterministic survey ID and a private normalized report under `surveys/SURVEY_ID/report.json`. The report lists file hashes, content classifications, technical fields, conflicts, manifest findings, and `collection_exit_status: unknown` when files alone cannot establish status.

**Success criteria:** Import and report commands exit `0`; inspect `files`, `technical_field_conflicts`, `manifests`, `flashrom`, and `acpi` in the private report before drawing conclusions. Missing output is a collection gap; absence remains unknown.

**Common failure modes:** Missing local file, unsupported format, unsafe archive member, malformed archive, or parser size limit.

**Recovery or cleanup:** Keep the original archive unchanged. Review the rejection detail, obtain a lawful corrected archive if needed, and import it as a new input. Do not hand-extract a rejected archive into the repository.

**Privacy:** The source may contain identifiers, keys, certificates, and machine logs. The importer writes a normalized private report; it does not make the archive public-safe.

**Network required:** No.

**Physical hardware accessed:** No.

## D. Produce a reviewed case-study export

**Purpose:** Reduce a private survey to an allowlisted technical record for possible publication.

**Prerequisites:** Procedure C, a completed manual review of every preview field, and verified rights to publish the chosen facts. The tool cannot prove anonymity.

**Environment:** The development host. Preview and review happen in the private workspace. Publication is a separate decision.

**Inputs:** A private survey ID and a new destination file outside Git.

**Exact commands:**

```fish
umask 077
set -gx AMD_FW_WORKSPACE "$HOME/.local/state/amd-fw"
set -gx AMD_FW_SURVEY_ID "survey-replace-with-imported-id"
set -gx AMD_FW_EXPORT "$AMD_FW_WORKSPACE/operator/reviewed-case-study.json"
amd-fw --json --workspace "$AMD_FW_WORKSPACE" survey public-export "$AMD_FW_SURVEY_ID" > "$AMD_FW_WORKSPACE/operator/export-preview.json"
cat "$AMD_FW_WORKSPACE/operator/export-preview.json"
amd-fw --json --workspace "$AMD_FW_WORKSPACE" survey public-export "$AMD_FW_SURVEY_ID" --reviewed --output "$AMD_FW_EXPORT" > "$AMD_FW_WORKSPACE/operator/export-receipt.json"
```

Run the last command only after reviewing the preview and publication rights. It creates a new file and refuses to overwrite one.

**Expected outputs:** First, `status: review_required` and `written: false`; after review, a new JSON file and a receipt with `written: true`.

**Success criteria:** The reviewed export contains only approved fields, contains no raw logs or unique identifiers, and publication rights have been checked. A successful local export does not itself authorize uploading or posting it.

**Common failure modes:** Invalid survey ID, changed or unexpectedly identifying fields, missing review flag, or an existing destination.

**Recovery or cleanup:** Correct the survey ID or choose a new output path. If a field could identify a person or machine, withhold the export and revise the source or policy through code review; do not edit a public copy in place.

**Privacy:** Allowlisting reduces exposure but does not guarantee anonymity. Never upload a raw archive to a public issue.

**Network required:** No for export. A later publication would require its own reviewed destination and authorization.

**Physical hardware accessed:** No.

## E. Inspect an existing vendor firmware package offline

**Purpose:** Hash and inventory a lawfully obtained package without executing it.

**Prerequisites:** Procedure A, a regular non-symlink file, provenance for where the package came from, and the right to inspect it. Keep vendor inputs outside Git.

**Environment:** The development host, offline. Do not run a vendor installer or extract untrusted members as part of this command.

**Inputs:** The exact local package path, set below.

**Exact commands:**

```fish
umask 077
set -gx AMD_FW_FIRMWARE_FILE "/absolute/path/to/lawfully-obtained-package"
test -f "$AMD_FW_FIRMWARE_FILE"
sha256sum "$AMD_FW_FIRMWARE_FILE"
amd-fw --json firmware inspect "$AMD_FW_FIRMWARE_FILE"
```

**Expected outputs:** Size, SHA-256, outer-format label, and explicit `cryptographic_verification: not_performed`. Recognized outer formats include a bounds-consistent UEFI FMP capsule header, ZIP metadata, gzip, xz, cabinet, tar, and an opaque MZ header. Unrecognized bytes are `opaque`. ZIP members are listed from metadata; none are extracted.

**Success criteria:** The command exits `0`, the SHA-256 matches the separately recorded source hash, and the report's limited interpretation is retained with the package provenance.

**Common failure modes:** Missing input, symlink, oversized file, malformed archive metadata, or unknown format.

**Recovery or cleanup:** Verify the original vendor download or source record, retain the original bytes, and treat an unknown format as opaque. Do not force a parser, execute the file, or call a vendor update package a complete SPI backup.

**Privacy:** Packages can contain proprietary or device-specific data. Do not copy them into Git or a public issue without rights review.

**Network required:** No for inspection. Acquiring the package separately may require network access.

**Physical hardware accessed:** No.

## F. Add a processor or platform record

**Purpose:** Add evidence-backed identity and platform information without implying exact-board support.

**Prerequisites:** A primary source with an exact location and retrieval date; a reviewed identity including vendor, architecture, family/model/stepping where established, codename aliases, SoC path if any, and uncertainty. Read [evidence policy](docs/evidence-policy.md) and [support policy](docs/support-policy.md).

**Environment:** A development checkout. Editing bundled JSON is offline; source research may use the network.

**Inputs:** `src/amd_fw/data/targets.json` and `src/amd_fw/data/evidence.json`.

**Exact commands:**

```fish
set -q EDITOR; or set -gx EDITOR vi
$EDITOR src/amd_fw/data/evidence.json
$EDITOR src/amd_fw/data/targets.json
python -m json.tool src/amd_fw/data/evidence.json > /dev/null
python -m json.tool src/amd_fw/data/targets.json > /dev/null
amd-fw catalog validate
python -m unittest discover -s tests
git diff -- src/amd_fw/data/evidence.json src/amd_fw/data/targets.json
```

**Expected outputs:** Valid schema version 1 files, resolvable evidence references, and a new record that names only what its sources establish.

**Success criteria:** Catalog validation and tests exit `0`; source revision, location, claim, limitations, and aliases survive review. CPUID values must be tied to evidence. `x86_64` alone is not evidence that a processor is AMD.

**Common failure modes:** Duplicate ID, unresolved evidence reference, wrong field type, stale upstream source, or a marketing alias that conflates two silicon variants.

**Recovery or cleanup:** Revert only the unfinished JSON edits or correct the record and rerun validation. Keep research-only status when an exact board port has not been established.

**Privacy:** Use public source facts or a separately reviewed normalized export; never paste raw private survey data into the catalog.

**Network required:** For new primary-source research; not for local validation.

**Physical hardware accessed:** No.

## G. Add an exact board recipe

**Purpose:** Define an auditable pinned build for one upstream mainboard target.

**Prerequisites:** An exact board Kconfig symbol and source directory at a pinned commit, board revision constraints, reviewed required inputs and licenses, expected image structure, and tests. A CPU name cannot select or create a board port. Read [architecture](docs/architecture.md) and [licensing](docs/licensing.md).

**Environment:** A development checkout for edits; a separate private workspace for source and build trials.

**Inputs:** A new `src/amd_fw/data/recipes/TARGET.json`, a matching board record in `targets.json`, and evidence in `evidence.json`.

**Exact commands:**

```fish
set -q EDITOR; or set -gx EDITOR vi
set -gx AMD_FW_TARGET "reviewed-exact-board-id"
$EDITOR "src/amd_fw/data/recipes/$AMD_FW_TARGET.json"
$EDITOR src/amd_fw/data/targets.json
$EDITOR src/amd_fw/data/evidence.json
python -m json.tool "src/amd_fw/data/recipes/$AMD_FW_TARGET.json" > /dev/null
amd-fw catalog validate
amd-fw --json report "$AMD_FW_TARGET"
python -m unittest discover -s tests
git diff -- src/amd_fw/data/recipes src/amd_fw/data/targets.json src/amd_fw/data/evidence.json
```

**Expected outputs:** A recipe with an exact upstream commit and HTTPS source URLs, validated Kconfig assignments, required file SHA-256 hashes, dependency license references, and `publication_eligible: false` and `hardware_tested: false` until separate evidence exists.

**Success criteria:** The recipe loader accepts the ID, the catalog points to it, tests cover its target resolution and failure paths, and any claimed build status matches an observed run recorded in the handoff and ledger. A copied recipe with changed board labels does not meet this criterion.

**Common failure modes:** Wrong board symbol, missing binary requirement, incorrect source lock, unreviewed license, or an expected ROM layout copied from another board.

**Recovery or cleanup:** Keep the board record research-only while correcting the recipe. Revert any unsupported readiness claim, then rerun tests and an authorized local build before promotion.

**Privacy:** Recipe files and tests may contain only public hashes and synthetic data. Keep vendor binaries and private machine identifiers out of Git.

**Network required:** For source research and later explicit fetch; not for local schema checks.

**Physical hardware accessed:** No.

## H. Build a verified existing target

**Purpose:** Acquire pinned source inputs and build one exact board recipe. The example target is `pcengines-apu2`; consult the handoff for whether this project has actually completed this build. The same CLI accepts `starlabs-starbook-cezanne` after its own license review.

**Prerequisites:** Procedure A, at least 2 GiB free in the workspace filesystem, the exact host executable versions in `src/amd_fw/data/toolchain-lock.json`, working `bwrap` namespaces, and an operator decision on the recipe's restrictive binary input licenses. Review the license locations named by `amd-fw --json report pcengines-apu2` and upstream terms before the acknowledgment flag. This procedure does not grant redistribution rights.

**Environment:** The development host. `sources fetch` uses the network explicitly; `sources verify` and `build` use local inputs. The build process uses a network-unshared Bubblewrap workspace and bounded jobs and timeout.

**Inputs:** Bundled `pcengines-apu2` recipe, its exact locked coreboot, submodule, SeaBIOS commits, and required binary hashes.

**Exact commands:**

```fish
umask 077
set -gx AMD_FW_WORKSPACE "$HOME/.local/state/amd-fw"
mkdir -p "$AMD_FW_WORKSPACE/operator"
chmod 700 "$AMD_FW_WORKSPACE" "$AMD_FW_WORKSPACE/operator"
amd-fw --json report pcengines-apu2
python -c 'from amd_fw.building import verify_toolchain_lock; print(verify_toolchain_lock())'
amd-fw --json --workspace "$AMD_FW_WORKSPACE" sources fetch pcengines-apu2 --accept-restricted-license > "$AMD_FW_WORKSPACE/operator/fetch-apu2.json"
amd-fw --json --workspace "$AMD_FW_WORKSPACE" sources verify pcengines-apu2 > "$AMD_FW_WORKSPACE/operator/verify-apu2.json"
amd-fw --json --workspace "$AMD_FW_WORKSPACE" build pcengines-apu2 --jobs 2 --timeout 1200 > "$AMD_FW_WORKSPACE/operator/build-apu2.json"
set -gx AMD_FW_MANIFEST (python -c 'import json,sys; print(json.load(open(sys.argv[1]))["manifest_path"])' "$AMD_FW_WORKSPACE/operator/build-apu2.json")
set -gx AMD_FW_ARTIFACT (python -c 'import json,sys; print(json.load(open(sys.argv[1]))["artifact_path"])' "$AMD_FW_WORKSPACE/operator/build-apu2.json")
amd-fw --json artifacts inspect "$AMD_FW_ARTIFACT"
amd-fw --json artifacts verify "$AMD_FW_MANIFEST"
```

**Expected outputs:** A verified toolchain profile, fetch and verify receipts, a build response with paths, `build.log`, `cbfs.txt`, `manifest.json`, and `artifacts/coreboot.rom` under the returned run directory. The manifest records exact source commits, hashes for explicitly required inputs, executable versions and lock hash, config hash, artifact digest, structural checks, and `hardware_tested: false`. Its `component_inventory_scope` identifies the limits of the curated inventory. In particular, additional Cezanne PSP files referenced by pinned upstream `fw.cfg` may be incorporated without individual hashes in the manifest.

**Success criteria:** Every command exits `0`; verification confirms exact source commits and hashes; the build response reports `validation_status: build_verified`; and `artifacts verify` accepts the returned manifest. This establishes a local build and static checks only.

**Common failure modes:** Network fetch failure, a host executable version outside the lock, missing build tool or namespace support, a wrong source commit or hash, insufficient disk space, timeout, Kconfig selection failure, or an image that fails size, FMAP, CBFS, or embedded-region checks.

**Recovery or cleanup:** Keep `fetch.log`, `build.log`, and the failed run directory. Fix the named input or host issue and rerun the failing command. Do not substitute bytes from another board or delete source evidence to make a check pass.

**Privacy:** Upstream checkouts, binary inputs, logs, manifests, and ROM images remain in the private workspace and outside Git. The license acknowledgment records local use only.

**Network required:** Yes for `sources fetch`; no for verify, build, and artifact checks.

**Physical hardware accessed:** No.

## I. Reproduce an artifact

**Purpose:** Compare two independent clean local builds of an exact recipe.

**Prerequisites:** A completed H source fetch and license decision, sufficient disk for two new build trees, and the same pinned input set. This command builds twice; it does not merely compare a supplied ROM with itself.

**Environment:** The development host, with network-unshared build sandboxes.

**Inputs:** A target ID and verified local source workspace.

**Exact commands:**

```fish
umask 077
set -gx AMD_FW_WORKSPACE "$HOME/.local/state/amd-fw"
amd-fw --json --workspace "$AMD_FW_WORKSPACE" sources verify pcengines-apu2
amd-fw --json --workspace "$AMD_FW_WORKSPACE" reproduce pcengines-apu2 --jobs 2 --timeout 1200 > "$AMD_FW_WORKSPACE/operator/reproduce-apu2.json"
cat "$AMD_FW_WORKSPACE/operator/reproduce-apu2.json"
```

**Expected outputs:** Two new build manifests, two SHA-256 values, `first_difference_offset` on a mismatch, and a saved `reproduce-*.json` report path.

**Success criteria:** Both builds complete and `status: reproducible` with equal artifact hashes. This result is limited to the recorded input set and one host environment matching the lock. The lock does not freeze every operating-system library or the kernel, and matching bytes do not establish boot or security properties.

**Common failure modes:** Either build can fail, or the two images can differ because of timestamps, nondeterministic tooling, or changed inputs.

**Recovery or cleanup:** Preserve both manifests, logs, ROMs, and the mismatch report. Record the first difference and investigate before claiming reproducibility. Rebuild after a documented fix; never relabel a mismatch as a pass.

**Privacy:** Comparison reports reveal private workspace paths and output hashes; keep them with build evidence outside Git until reviewed.

**Network required:** No after sources are present.

**Physical hardware accessed:** No.

## J. Handle missing binary inputs

**Purpose:** Identify an exact required component and refuse missing or mismatched bytes.

**Prerequisites:** A selected recipe and knowledge of its legal input source and license terms. The recipe specifies expected relative paths and SHA-256 hashes.

**Environment:** The development host. Verification is offline; acquisition by the current adapter is through explicit `sources fetch` at pinned upstream revisions.

**Inputs:** The recipe and its local `sources/coreboot` tree.

**Exact commands:**

```fish
set -gx AMD_FW_WORKSPACE "$HOME/.local/state/amd-fw"
amd-fw --json report pcengines-apu2
amd-fw --json --workspace "$AMD_FW_WORKSPACE" sources verify pcengines-apu2
```

The current recipes expect their binary inputs in pinned upstream checkouts. `sources verify` checks the listed SHA-256 values and source revisions. The build copies that checkout and removes untracked and ignored files from the disposable copy before compiling. An extra file placed manually in the source cache can therefore pass an initial hash check yet be removed before the build. Do not use manual placement as an input-staging procedure. A future recipe requiring a separately supplied file needs an explicit, reviewed staging path that preserves the file through the clean copy and verifies its license and hash.

**Expected outputs:** Either `status: verified` with input hashes or an error naming the missing path or checksum mismatch.

**Success criteria:** All required bytes match their recipe hashes and the operator has reviewed each applicable license. No dummy or substitute input was used.

**Common failure modes:** Missing pinned input, wrong source revision, hash mismatch, unreviewed restrictive terms, or an added file removed during build-copy cleanup.

**Recovery or cleanup:** Obtain the exact permitted version, update a recipe only after evidence and review, or mark the target `inputs-missing`. Keep an unresolved licensing question as a blocker. Never bypass a signature or platform security control.

**Privacy:** Binary inputs stay outside Git and are never uploaded by `sources verify`.

**Network required:** No for verification; possibly for explicitly authorized input acquisition.

**Physical hardware accessed:** No.

## K. Update an upstream dependency

**Purpose:** Change a pinned coreboot, submodule, payload, or toolchain version with traceable impact.

**Prerequisites:** A reviewed upstream change, exact commit, release and source locations, current license terms, and a baseline build result. Review the affected target records, recipe hashes, and the executable lock in `src/amd_fw/data/toolchain-lock.json`.

**Environment:** A development checkout plus a separate private build workspace. Research and fetch may require network access.

**Inputs:** Recipe JSON, target and evidence records, source lock, dependency licenses, and prior manifests.

**Exact commands:**

```fish
set -q EDITOR; or set -gx EDITOR vi
$EDITOR src/amd_fw/data/evidence.json
$EDITOR src/amd_fw/data/targets.json
$EDITOR src/amd_fw/data/recipes/pcengines-apu2.json
$EDITOR src/amd_fw/data/toolchain-lock.json
amd-fw catalog validate
python -m unittest discover -s tests
python -c 'from amd_fw.building import verify_toolchain_lock; print(verify_toolchain_lock())'
git diff -- src/amd_fw/data/evidence.json src/amd_fw/data/targets.json src/amd_fw/data/recipes/pcengines-apu2.json src/amd_fw/data/toolchain-lock.json
```

Edit the lock only when changing or verifying its executable profile. Record the exact version strings from the new host, review the compiler and dependency license effects, then run a fresh build and two-build reproduction before claiming a new profile works. The lock covers executable versions; it does not freeze every host library or kernel. After review, use a new private workspace and procedures H and I for a real fetch, build, and comparison. Do not mutate an existing pinned checkout to masquerade as the old baseline.

**Expected outputs:** A diff recording all changed commits, input hashes, license references, executable versions when changed, expected image checks, evidence dates, and any status change, followed by new build manifests if the build is executed.

**Success criteria:** Catalog and tests pass; license and security impact is reviewed; the new source passes verification and the claimed build checks. Compare old and new artifact hashes and note any regressions or changed output structure. Reproducibility requires a fresh two-build result.

**Common failure modes:** Stale submodule pin, changed binary hash, executable lock mismatch, new license term, unexpected board Kconfig change, or build regression.

**Recovery or cleanup:** Retain both old and new manifests. Revert only the reviewed dependency change if it is defective, then rerun validation. Do not force a status promotion to hide failure.

**Privacy:** Keep downloaded inputs and generated outputs in private workspaces; only reviewed metadata and source edits enter Git.

**Network required:** Yes for research and explicit fetch; no for local validation and builds after acquisition.

**Physical hardware accessed:** No.

## L. Diagnose a failure

**Purpose:** Classify a failure before retrying or changing evidence claims.

**Prerequisites:** The failed command, its exit status, standard error, and any returned log or manifest path.

**Environment:** Development host; inspect files locally. A retry is a separate explicit action.

**Inputs:** The failed result and private workspace paths, if any.

**Exact commands:**

```fish
set -gx AMD_FW_WORKSPACE "$HOME/.local/state/amd-fw"
amd-fw --json doctor
amd-fw catalog validate
amd-fw --json --workspace "$AMD_FW_WORKSPACE" sources verify pcengines-apu2
test -d "$AMD_FW_WORKSPACE/builds"; and find "$AMD_FW_WORKSPACE/builds" -maxdepth 4 -name build.log -print
```

Use `tail -n 80 "/exact/path/from/result/build.log"` only after checking the returned path. For a failed reproduction, inspect both `first_manifest` and `second_manifest` from the saved comparison report.

For an optional virtual smoke check, follow the [generic i440fx test procedure](docs/research/generic-qemu-smoke.md) to create its own ROM, then run the bounded harness with explicit local paths:

```fish
set -gx AMD_FW_GENERIC_ROM "/absolute/path/to/generic-i440fx-coreboot.rom"
set -gx AMD_FW_QEMU "/absolute/path/to/qemu-system-x86_64"
python tools/generic_smoke.py --rom "$AMD_FW_GENERIC_ROM" --qemu "$AMD_FW_QEMU" --timeout 30
```

QEMU is optional and is not currently on this development host's normal `PATH`. The harness requires both a serial marker and a guest debug-exit signal; it returns `77` when QEMU is unavailable. Its result applies only to the generic virtual i440fx path and does not validate either AMD board recipe.

**Expected outputs:** Tool inventory, catalog result, exact missing input or source mismatch, and paths to retained build logs.

**Success criteria:** Assign the failure to a concrete stage. Exit `3` means unsupported target; `4` means missing tool/input; `5` means integrity or schema issue; `6` means other operation failure. An `invalid_artifact` or parser rejection records a failed check and supplies no hardware evidence.

**Common failure modes:** Missing dependency or executable-lock mismatch, unavailable source, checksum mismatch, schema error, parser rejection, build or Kconfig error, disk or timeout limit, unavailable QEMU, generic smoke timeout, or differing hashes. The generic smoke script reports its own status separately from AMD board build results.

**Recovery or cleanup:** Fix only the identified cause, keep logs, and rerun the smallest relevant check. Update the handoff with failures and skips. If the tool lacks a retry-safe state, preserve the failed workspace and start a new one rather than deleting evidence.

**Privacy:** Logs and reports can disclose local paths and input names; review before sharing.

**Network required:** No for these checks. Source reacquisition, if needed, is explicit and online.

**Physical hardware accessed:** No.

## M. Release engineering

**Purpose:** Prepare a software source release without promoting private or unvalidated firmware images.

**Prerequisites:** A reviewed version change and changelog, completed tests, current handoff, source and dependency licenses, provenance, privacy review, and a decision on repository visibility and release eligibility. Stage the exact candidate files before running the staged-content scanner below. Firmware image assets need a separate rights and validation review.

**Environment:** A clean development checkout. Local packaging may access the configured Python index for its pinned backend. Publishing occurs only through the authorized repository workflow.

**Inputs:** Reviewed tracked files and the exact release commit.

**Exact commands:**

```fish
umask 077
set -gx AMD_FW_RELEASE_DIR (mktemp -d -t amd-fw-release.XXXXXX)
git status --short
git diff --check
amd-fw catalog validate
python -m unittest discover -s tests
python tools/check_staged.py
git log --format='%h %s' > "$AMD_FW_RELEASE_DIR/changes.txt"
python -m pip wheel . --no-deps --wheel-dir "$AMD_FW_RELEASE_DIR"
sha256sum "$AMD_FW_RELEASE_DIR"/*.whl
```

Edit the changelog from reviewed commits and set the version in `pyproject.toml` and `src/amd_fw/__init__.py` consistently before packaging. Run the staged scanner again after staging the release diff. Do not publish until the exact candidate commit, visibility, licenses, generated wheel, and release assets have been reviewed.

**Expected outputs:** Test results, a staged-content scan, draft changes list, and a local wheel with SHA-256. No firmware ROM is an automatic release asset.

**Success criteria:** All required checks pass; the handoff states actual build, reproducibility, CI, and hardware statuses; the reviewed software package contains no private evidence or restricted binaries; release eligibility is recorded explicitly.

**Common failure modes:** Test or lint regression, stale version, missing license notice, a forbidden staged archive or identifier, wheel build failure, or a release artifact whose rights are unresolved.

**Recovery or cleanup:** Correct the candidate and rebuild. If a defective software release was already published, create a reviewed fix and use `git revert "$BAD_COMMIT"` on an appropriate branch when that commit is the cause; publish a corrected release through the repository's normal process. Do not rewrite shared history or describe this as firmware rollback.

**Privacy:** The scanner is one gate. Inspect staged paths and text manually. Keep generated ROMs, surveys, and vendor inputs outside Git and release assets.

**Network required:** Possibly for packaging dependencies and repository publication; local review commands are offline.

**Physical hardware accessed:** No.

## N. Resume after an interrupted session

**Purpose:** Reconcile durable state before continuing work or repeating an expensive operation.

**Prerequisites:** This checkout, [PROJECT_HANDOFF.md](PROJECT_HANDOFF.md), the evidence and progress ledgers named there, and access to the same private workspace when needed.

**Environment:** Development host, initially offline.

**Inputs:** Git state, handoff, ledgers, prior results, and workspace manifests.

**Exact commands:**

```fish
git branch --show-current
git status --short
git log -1 --format='%H %s'
cat PROJECT_HANDOFF.md
amd-fw --json doctor
amd-fw catalog validate
python -m unittest discover -s tests
```

Then run only the next command named in the handoff after confirming its prerequisites. Inspect private logs by their recorded paths; do not assume an archive or checkout exists because an earlier chat mentioned one.

**Expected outputs:** Current branch and commit, dirty paths, completed and failed checks, blocked tasks, and exact next work.

**Success criteria:** The resumed operator can distinguish planned work from observed results and identify the last validated commit and current private workspace without repeating an irreversible or expensive step by accident.

**Common failure modes:** Missing handoff, stale ledger, detached or unexpected branch, missing private workspace, or a report referring to a different source lock.

**Recovery or cleanup:** Stop the affected lane, compare Git state with manifests and logs, update the handoff with the discrepancy, and resume from the last confirmed checkpoint. Preserve failed outputs.

**Privacy:** The handoff may name private locations; do not copy their contents into public issue text.

**Network required:** No for reconciliation; only a later explicit fetch or push needs it.

**Physical hardware accessed:** No.

## O. Future physical-hardware validation governance

**Purpose:** State the gate for a future, separately authorized validation campaign. This project does not authorize or perform physical validation, and Momiji is excluded from physical experimentation.

**Prerequisites:** Independent ownership and explicit action-specific authorization for a different test board; exact model and revision; independently established recovery capability; an experienced operator; artifact SHA-256 and provenance; a written test plan, abort conditions, and a way to record outcomes.

**Environment:** A future human-supervised hardware lab under a separate authorization. No lab command is part of this runbook.

**Inputs:** A reviewed plan and exact artifact identity, only after the gates above are met.

**Exact commands:** None. This section intentionally gives governance checks only. The current CLI offers no flashing command.

**Expected outputs:** Before any separate future operation, a signed-off plan naming the board, revision, operator, artifact, recovery approach, and scope. No hardware result is produced by this procedure.

**Success criteria:** The current project stays at `hardware: not_performed` until independently documented, separately authorized evidence exists for an exact board and artifact.

**Common failure modes:** A CPU-family match mistaken for board support, no recovery path, unclear ownership, unidentified artifact, or a plan that silently includes Momiji.

**Recovery or cleanup:** Keep the target research-only or build-only; revise the governance plan without touching hardware.

**Privacy:** Any future lab record must be reviewed for identifiers before publication.

**Network required:** No current network operation.

**Physical hardware accessed:** No. A future operation needs separate authorization and documentation.

## P. Back up and clean the development workspace

**Purpose:** Preserve code, reproducible inputs, generated outputs, and private evidence separately, then remove one explicitly selected project-owned target build directory.

**Prerequisites:** A reviewed backup destination outside Git, enough free space, and a completed handoff. A Git bundle requires at least one commit. For cleanup, choose one exact target whose build directory was created by this project. The command does not delete `sources/`, `surveys/`, the whole workspace, or unrelated user files.

**Environment:** Development host. Keep private backups on storage with appropriate access controls.

**Inputs:** Git checkout, private workspace, and an exact target ID for optional cleanup.

**Exact commands:**

```fish
umask 077
set -gx AMD_FW_WORKSPACE "$HOME/.local/state/amd-fw"
set -gx AMD_FW_BACKUP_PARENT "/absolute/path/to/restricted-backup"
test -d "$AMD_FW_BACKUP_PARENT"
set -gx AMD_FW_BACKUP_DIR (mktemp -d "$AMD_FW_BACKUP_PARENT/amd-fw.XXXXXXXX")
chmod 700 "$AMD_FW_BACKUP_DIR"
git status --short
git rev-parse HEAD
git bundle create "$AMD_FW_BACKUP_DIR/source.bundle" --all
cp -a "$AMD_FW_WORKSPACE/sources" "$AMD_FW_BACKUP_DIR/"
cp -a "$AMD_FW_WORKSPACE/surveys" "$AMD_FW_BACKUP_DIR/"
cp -a "$AMD_FW_WORKSPACE/builds" "$AMD_FW_BACKUP_DIR/"
```

Skip a `cp` command only when that category does not exist. The source bundle includes commits and refs. Record uncommitted edits separately after reviewing them. The cleanup command removes all runs for one named target, so inspect and back up its logs, manifests, reports, and artifacts first:

```fish
set -gx AMD_FW_TARGET "pcengines-apu2"
find "$AMD_FW_WORKSPACE/builds/$AMD_FW_TARGET" -maxdepth 2 -type f -print
amd-fw --json --workspace "$AMD_FW_WORKSPACE" workspace clean "$AMD_FW_TARGET"
```

**Expected outputs:** Separate private copies of source history, pinned inputs, survey reports, and generated build evidence. Cleanup returns `status: removed` or `status: absent`; it verifies the project ownership marker before removing the selected target build directory.

**Success criteria:** Backup files are readable, the private destination has owner-only access, and the handoff records what was backed up and deleted. Source evidence and raw private inputs are retained unless the owner directs otherwise.

**Common failure modes:** Missing category directory, insufficient backup space, no commit for the source bundle, uncommitted work missing from that bundle, wrong target path, or marker mismatch.

**Recovery or cleanup:** Stop on a failed copy and inspect the destination before retrying. `workspace clean` fails closed on a path or marker mismatch. Do not use a recursive delete on the entire workspace.

**Privacy:** These backups may contain restricted firmware and private hardware evidence. Keep them outside Git and public cloud storage unless the owner has separately reviewed access and rights.

**Network required:** No for local backup and cleanup.

**Physical hardware accessed:** No.
