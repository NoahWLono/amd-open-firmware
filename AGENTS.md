# Repository operating boundaries

The project owner is Noah Weinberger. Work here concerns an independent AMD
open-firmware research and build system. Consult `PROJECT_HANDOFF.md` and
`RUNBOOK.md` before resuming work.

Do not access, probe, flash, unlock, erase, read, or alter firmware hardware,
SPI, EC, SMBus, I2C, TPM state, fuses, Secure Boot keys, or boot variables.
Momiji is excluded from physical experimentation. Do not run `flashrom` on an
internal programmer, even for `--flash-name`.

Keep raw surveys, vendor packages, binary inputs, upstream checkouts, and
generated firmware outside Git. Treat all imported material as private unless
the owner has reviewed a normalized allowlist export. Never infer a board port
from a CPU name. A build passing is not boot or hardware validation.

Document exact upstream commits, source locations, dependency licenses, test
commands, failures, and any publication gate. Use Fish-compatible commands in
the operator runbook. Do not add automatic flashing or protection bypasses.
