# Generic coreboot QEMU smoke test

This optional test checks that a coreboot `emulation/qemu-i440fx` image built
from a pinned source revision can load a small ELF payload. The payload prints
`AMD_FW_GENERIC_QEMU_PAYLOAD_OK` on QEMU's emulated COM1 port and writes `0x10`
to an explicitly configured QEMU ISA debug-exit device. The harness requires
both the serial marker and QEMU process exit code 33. It runs with TCG, no
network device, and no physical-device passthrough.

The result says nothing about AMD silicon initialization, an AMD board ROM,
Momiji, physical boot, or the safety of installing firmware. The generic ROM
and logs remain outside Git. This ROM has not passed a release licensing
review.

## Source and local prerequisites

- coreboot 26.06 commit `5cbf8afc4c08949c9b4ee1cb9dc5439add8a937e`,
  from `https://review.coreboot.org/coreboot.git`, with its build dependencies
  available in a prepared checkout. The upstream board files are under
  `src/mainboard/emulation/qemu-i440fx/`; upstream execution guidance is in
  `Documentation/mainboard/emulation/qemu-i440fx.md` at that commit.
- GNU assembler, linker, `make`, GCC, and IASL. This run used GCC 16.2.1 and
  IASL 20251212. `CONFIG_ANY_TOOLCHAIN=y` allowed the system GCC. Coreboot
  explicitly marks that choice unsupported. It was a practical local smoke
  build choice. Production firmware needs a qualified toolchain.
- `qemu-system-x86_64`. The host used a separate local QEMU 11.1.1 bundle;
  QEMU was absent from the normal `PATH`. Its binary provenance was not
  independently audited. No package was installed on the host.

The following commands are Fish compatible. Set `source_root` to a prepared,
pinned coreboot checkout and `qemu_bin` to a QEMU executable or wrapper. The
copy keeps configuration and generated files away from the source cache used
by AMD board builds.

```fish
set -l source_root /path/to/pinned/coreboot
set -l qemu_bin /path/to/qemu-system-x86_64
set -l smoke_root (mktemp -d /tmp/amd-fw-qemu.XXXXXX)
cp -a "$source_root" "$smoke_root/coreboot"
git -C "$smoke_root/coreboot" rev-parse HEAD

as --32 -o "$smoke_root/payload.o" tools/generic_smoke_payload.S
ld -m elf_i386 --build-id=none -T tools/generic_smoke_payload.ld \
  -o "$smoke_root/payload.elf" "$smoke_root/payload.o"

printf '%s\n' \
  'CONFIG_VENDOR_EMULATION=y' \
  'CONFIG_BOARD_EMULATION_QEMU_X86_I440FX=y' \
  'CONFIG_ANY_TOOLCHAIN=y' \
  'CONFIG_PAYLOAD_ELF=y' \
  "CONFIG_PAYLOAD_FILE=\"$smoke_root/payload.elf\"" \
  'CONFIG_COMPRESSED_PAYLOAD_NONE=y' \
  'CONFIG_CONSOLE_SERIAL=y' \
  'CONFIG_CONSOLE_QEMU_DEBUGCON_PORT=0x402' \
  'CONFIG_DEFAULT_CONSOLE_LOGLEVEL_7=y' \
  > "$smoke_root/coreboot/defconfig"

make -C "$smoke_root/coreboot" defconfig \
  KBUILD_DEFCONFIG="$smoke_root/coreboot/defconfig"
make -C "$smoke_root/coreboot" -j2 BUILD_TIMELESS=1 UPDATED_SUBMODULES=1
python3 tools/generic_smoke.py \
  --rom "$smoke_root/coreboot/build/coreboot.rom" \
  --qemu "$qemu_bin" --timeout 30
```

`git rev-parse HEAD` must print the pinned commit above before building.
`make` should end with `Built emulation/qemu-i440fx (QEMU x86 i440fx/piix4)`.
The harness returns JSON with `status: "passed"`,
`serial_success_signal_seen: true`, and `qemu_exit_code: 33` only when both
guest signals arrive. Exit code 77 means QEMU is unavailable. Missing marker,
wrong exit code, output limit, or timeout count as failures.
The harness also rejects empty ROMs and ROMs larger than 64 MiB before
launching QEMU.

## Observed local run on 2026-09-22

The generic image built successfully. CBFS contained `fallback/payload` as a
simple ELF payload. The 4 MiB ROM SHA-256 was
`544bde9eec85b4e7d1d36add97bd4d3a68d3bfa7661bbbe0c00e0087bd440b58`.
The payload ELF SHA-256 was
`f671509d94e03154d4543b0a424fa4b1eb48e15fb426c3aef159f98a6ebf7747`.
Two QEMU 11.1.1 runs returned exit code 33 and showed the serial marker. They
took 0.347 and 0.248 seconds. The first had 14,307 serial bytes with SHA-256
`8993232ef5f4502c4870b75f5d9acd1168a36944aa07763b57b02cee160d62f8`;
the second had 14,306 bytes. The serial transcript varied between runs, so
the test checks the marker and controlled exit rather than a full log digest.
The recorded ROM digest identifies this one local artifact; changing a path,
compiler, or configuration can change the bytes. No repeat-build comparison
was made for this generic image.
