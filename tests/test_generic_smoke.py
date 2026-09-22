"""Failure classification for the optional generic QEMU smoke harness."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.generic_smoke import main


class GenericSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.rom = self.root / "generic.rom"
        self.rom.write_bytes(b"synthetic ROM placeholder")

    def _fake_qemu(self, body: str) -> Path:
        executable = self.root / "fake-qemu"
        executable.write_text("#!/bin/sh\n" + body, encoding="utf-8")
        executable.chmod(0o700)
        return executable

    def _run(self, qemu: Path, timeout: str = "1") -> tuple[int, dict[str, object]]:
        from io import StringIO

        output = StringIO()
        with patch("sys.stdout", output):
            exit_code = main(
                [
                    "--rom",
                    str(self.rom),
                    "--qemu",
                    str(qemu),
                    "--timeout",
                    timeout,
                ]
            )
        return exit_code, json.loads(output.getvalue())

    def test_requires_both_serial_marker_and_debug_exit(self) -> None:
        qemu = self._fake_qemu(
            "printf 'AMD_FW_GENERIC_QEMU_PAYLOAD_OK\\r\\n'\nexit 33\n"
        )
        exit_code, report = self._run(qemu)
        self.assertEqual(exit_code, 0)
        self.assertEqual(report["status"], "passed")
        self.assertFalse(report["amd_silicon_validation"])

        qemu = self._fake_qemu(
            "printf 'AMD_FW_GENERIC_QEMU_PAYLOAD_OK\\r\\n'\nexit 0\n"
        )
        exit_code, report = self._run(qemu)
        self.assertEqual(exit_code, 1)
        self.assertEqual(report["reason"], "guest_debug_exit_code_mismatch")

    def test_missing_marker_and_timeout_fail_closed(self) -> None:
        qemu = self._fake_qemu("printf 'firmware started\\n'\nexit 33\n")
        exit_code, report = self._run(qemu)
        self.assertEqual(exit_code, 1)
        self.assertEqual(report["reason"], "serial_success_signal_missing")

        qemu = self._fake_qemu("sleep 2\n")
        exit_code, report = self._run(qemu, timeout="0.1")
        self.assertEqual(exit_code, 1)
        self.assertEqual(report["reason"], "timeout")

    def test_oversized_rom_is_rejected_before_qemu_launch(self) -> None:
        with self.rom.open("wb") as stream:
            stream.truncate(64 * 1024 * 1024 + 1)
        qemu = self._fake_qemu("exit 33\n")
        with patch(
            "tools.generic_smoke.run_smoke", side_effect=AssertionError("QEMU launched")
        ):
            exit_code, report = self._run(qemu)
        self.assertEqual(exit_code, 2)
        self.assertEqual(report["status"], "invalid_input")


if __name__ == "__main__":
    unittest.main()
