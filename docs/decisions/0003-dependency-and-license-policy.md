# ADR 0003: Firmware inputs and licensing

Date: 2026-09-22
Status: accepted for the initial implementation
Owner: Noah Weinberger

## Decision

Original Python tooling and documentation use Apache-2.0. Coreboot,
SeaBIOS, their submodules, and every binary input retain their upstream
terms. Recipes identify upstream source revisions, required binary paths,
expected SHA-256 digests, roles, and license documents. Restricted inputs
require an explicit local license decision before source acquisition. The
decision records that an operator acknowledged local use; it does not grant
redistribution rights.

Source fetching and building use a private workspace. Neither Git nor normal
CI contains downloaded source trees, binary inputs, or ROM images. Firmware
artifact publication remains disabled for both initial recipes because their
binary inputs and board validation need a separate release review.

## Consequences

Public availability of an input is insufficient evidence for redistribution.
A recipe must fail when an input is absent or differs from its pinned hash.
It must never substitute another board's input or placeholder bytes. A future
recipe with user-supplied inputs needs a documented source, hash, role, and
license decision. If rights remain unclear, the artifact stays private.

See `docs/licensing.md` for the repository license boundary and the recipe
files for the current per-input records. Any newly vendored code requires
its own notice and licensing review.
