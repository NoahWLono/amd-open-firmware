# Upstream strategy

Coreboot owns mainboard, SoC, and build integration code that applies broadly.
openSIL owns its silicon-initialization libraries. Payload projects own their
payloads. Vendor repositories own vendor-distributed inputs. This repository
owns target selection, source locks, dependency accounting, safe offline
inspection, reproducible build orchestration, and provenance reports.

Contribute fixes to the relevant upstream when practical. Do not copy a board
directory into this project merely to claim support. A reviewed downstream
port would need its own source revision, board revision constraints, test
evidence, and maintenance plan. The initial recipes reference exact coreboot
targets without changing their implementation.
