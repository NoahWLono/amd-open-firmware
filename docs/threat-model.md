# Threat model

The project processes archives and firmware files that may be malformed or
malicious. It can fetch upstream source and run large native build systems.
The principal risks are unsafe archive paths or links, decompression bombs,
parser overreads, unexpected network input, supply-chain changes, accidental
publication of private data, false compatibility claims, and accidental
hardware access.

The importer bounds members and expanded bytes and does not execute archive
content. The inspector reports opaque data where a format is not understood.
Source acquisition is explicit and pinned; build commands verify local inputs
and do not silently fetch. Subprocesses use argument arrays and bounded logs.
The standard workflow contains no flasher and needs no root privilege or
device passthrough. Public exports are allowlisted and require review.

These controls do not prove firmware safety. A malicious upstream build system,
compromised compiler, incorrectly classified binary input, or human decision
to flash an untested artifact can still cause harm. Private repository
visibility is a safeguard for this initial project, not a substitute for
removing sensitive content from Git history.
