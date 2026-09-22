# Architecture

The package has five boundaries. `catalog.py` loads versioned, packaged JSON
and validates evidence references and exact-board build claims. `offline.py`
reads untrusted survey archives and firmware files without executing content.
`building.py` implements pinned source acquisition, verification, isolated
builds, manifests, and comparison. `workspace.py` removes only an explicitly
named, marked target build directory. `cli.py` is the only command line entry
point and maps operation outcomes to stable exit codes. The separate
`tools/generic_smoke.py` harness tests a QEMU virtual path with an explicit
guest signal; it does not assess AMD board boot.

The catalog uses identifiers for processors or SoCs, exact mainboard targets,
recipes, and research cases. Relationships identify the links; they do not
promote a CPU to board support. The `evidence.json` ledger records each
source, exact location, revision, retrieval date, supported assertion, and
limit. Schema version 1 is rejected if a future file changes its version;
there is no silent migration.

Source fetching is explicit. It writes to a chosen workspace. A later build
verifies pinned revisions and required inputs, executes a bounded upstream
build with no device passthrough, then records output hashes and provenance.
Reports separate static image checks from emulator and physical validation.
The private workspace also contains imported survey reports. It is not part
of the source repository.

To add an upstream board, add source evidence first, record the exact
mainboard symbol and board revision constraints, then create a recipe with
pinned sources and dependency policy. Add a test for target resolution and a
real build result before claiming `build-verified`.
