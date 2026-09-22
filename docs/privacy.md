# Private evidence and public exports

Survey archives may contain serial numbers, UUIDs, MAC addresses, disk and
partition identifiers, hostnames, usernames, EFI variables, certificates, and
firmware binaries. Importing one does not rerun a command. The raw archive and
private normalized report belong in a restricted workspace outside this Git
checkout.

Public export uses a named allowlist of technical fields and omits raw logs,
opaque files, unique machine identifiers, and source paths. The CLI first
produces a preview. A person must review it before writing the export with
the explicit review flag. This is a reduction of exposure, not a guarantee of
anonymity. Never attach a raw survey to a public issue. A hardware survey is
not by itself proof of a working firmware port.

Before a commit or release, inspect the exact staged paths, search staged text
for secrets and device identifiers, and reject archive and firmware binary
extensions. `.gitignore` prevents ordinary accidents but does not secure
explicitly added files.
