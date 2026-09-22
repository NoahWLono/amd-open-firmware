#!/usr/bin/env python3
"""Run a bounded generic coreboot x86 payload smoke test in QEMU TCG.

The ROM must contain tools/generic_smoke_payload.S. This checks only QEMU's
generic i440fx firmware path. It makes no AMD silicon or hardware claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import selectors
import shutil
import signal
import subprocess
import sys
import time

SUCCESS_SIGNAL = b"AMD_FW_GENERIC_QEMU_PAYLOAD_OK"
SUCCESS_EXIT = 33  # QEMU isa-debug-exit maps guest byte 0x10 to (0x10 << 1) | 1.
MAX_SERIAL_BYTES = 1_048_576
MAX_ROM_BYTES = 64 * 1024 * 1024


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _stop(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait()


def run_smoke(qemu: str, rom: Path, timeout_seconds: float) -> dict[str, object]:
    """Boot a ROM with emulated devices only and check both guest signals."""
    command = [
        qemu,
        "-nodefaults",
        "-no-user-config",
        "-machine",
        "pc,accel=tcg",
        "-cpu",
        "qemu32",
        "-m",
        "256M",
        "-smp",
        "1",
        "-display",
        "none",
        "-monitor",
        "none",
        "-serial",
        "stdio",
        "-net",
        "none",
        "-no-reboot",
        "-bios",
        str(rom),
        "-device",
        "isa-debug-exit,iobase=0xf4,iosize=0x04",
    ]
    start = time.monotonic()
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except OSError as exc:
        return {
            "status": "unavailable",
            "reason": f"QEMU could not start: {exc.strerror or type(exc).__name__}",
        }

    assert process.stdout is not None
    output = bytearray()
    reason: str | None = None
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                remaining = timeout_seconds - (time.monotonic() - start)
                if remaining <= 0:
                    reason = "timeout"
                    break
                for key, _ in selector.select(timeout=min(remaining, 0.1)):
                    block = os.read(key.fileobj.fileno(), 65_536)
                    if not block:
                        selector.unregister(key.fileobj)
                        continue
                    output.extend(block)
                    if len(output) > MAX_SERIAL_BYTES:
                        reason = "serial_output_limit_exceeded"
                        break
                if reason is not None:
                    break
                if process.poll() is not None and not selector.get_map():
                    break
    finally:
        _stop(process)
        process.stdout.close()
    elapsed = round(time.monotonic() - start, 3)
    signal_seen = SUCCESS_SIGNAL in output
    exit_code = process.returncode
    if reason is None and not signal_seen:
        reason = "serial_success_signal_missing"
    if reason is None and exit_code != SUCCESS_EXIT:
        reason = "guest_debug_exit_code_mismatch"
    return {
        "status": "passed" if reason is None else "failed",
        "reason": reason,
        "qemu_exit_code": exit_code,
        "expected_exit_code": SUCCESS_EXIT,
        "serial_success_signal_seen": signal_seen,
        "serial_bytes": len(output),
        "serial_sha256": hashlib.sha256(output).hexdigest(),
        "elapsed_seconds": elapsed,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rom", type=Path, required=True, help="generic QEMU coreboot ROM"
    )
    parser.add_argument("--qemu", help="qemu-system-x86_64 executable or wrapper")
    parser.add_argument(
        "--timeout", type=float, default=30.0, help="seconds (default: 30)"
    )
    args = parser.parse_args(argv)

    report: dict[str, object] = {
        "schema_version": 1,
        "test": "generic_coreboot_i440fx_qemu",
        "physical_hardware_access": False,
        "amd_silicon_validation": False,
    }
    if not math.isfinite(args.timeout) or args.timeout <= 0 or args.timeout > 120:
        report.update(
            status="invalid_input", reason="timeout must be in (0, 120] seconds"
        )
        print(json.dumps(report, sort_keys=True))
        return 2
    if not args.rom.is_file() or args.rom.is_symlink():
        report.update(
            status="invalid_input", reason="ROM must be a regular, non-symlink file"
        )
        print(json.dumps(report, sort_keys=True))
        return 2
    rom_size = args.rom.stat().st_size
    if not 0 < rom_size <= MAX_ROM_BYTES:
        report.update(
            status="invalid_input", reason="ROM size must be between 1 byte and 64 MiB"
        )
        print(json.dumps(report, sort_keys=True))
        return 2
    qemu = args.qemu or shutil.which("qemu-system-x86_64")
    if not qemu:
        report.update(status="unavailable", reason="qemu-system-x86_64 not found")
        print(json.dumps(report, sort_keys=True))
        return 77
    report["rom_sha256"] = _sha256(args.rom)
    report.update(run_smoke(qemu, args.rom, args.timeout))
    print(json.dumps(report, sort_keys=True))
    return {"passed": 0, "failed": 1, "invalid_input": 2, "unavailable": 77}[
        str(report["status"])
    ]


if __name__ == "__main__":
    sys.exit(main())
