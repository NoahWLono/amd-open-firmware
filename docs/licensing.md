# Licensing and distribution

Original Python tooling and original documentation in this repository are
licensed under Apache-2.0. The full text is in `LICENSE`. Copyright belongs
to Noah Weinberger for the original material. Upstream work belongs to its
respective authors; this repository neither vendors nor relicenses coreboot,
openSIL, payload projects, or vendor firmware.

Build recipes identify selected required inputs and their known licenses or
unresolved status. The manifest's component inventory has incomplete per-file
coverage. The pinned Star Labs blob tree licenses its `ec.bin` binary under
MIT, but keeps its source proprietary. That license does not cover the AMD
binary inputs in the assembled StarBook ROM. A public download is not evidence
of permission to bundle or redistribute a binary. The current adapter verifies
hashes for listed files in pinned upstream checkouts and never uploads them.
Separately supplied files need a reviewed staging path before they can be
used in a clean build. If distribution terms are unresolved, the artifact is
not an eligible release asset. A successful build does not override that
restriction.

The project is not endorsed by AMD, HP, coreboot, Libreboot, openSIL, or any
other named organization. Refer to source locks and component notices before
changing a dependency pin.
