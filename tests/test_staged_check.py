import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from check_staged import scan_index


class StagedCheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)

    def tearDown(self):
        self.temp.cleanup()

    def _stage(self, name: str, data: bytes):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        subprocess.run(["git", "-C", str(self.root), "add", "-f", name], check=True)

    def test_rejects_firmware_and_private_archive_extensions(self):
        self._stage("evidence/preflight.tar.gz", b"synthetic")
        self._stage("release/board.rom", b"synthetic")
        issues = scan_index(self.root)
        self.assertEqual(len(issues), 2)

    def test_rejects_secret_and_device_identifier_in_text(self):
        self._stage(
            "notes.txt",
            b"Serial Number: SYNTHETIC-UNIQUE-001\n"
            + b"-----BEGIN "
            + b"PRIVATE KEY-----\n",
        )
        issues = scan_index(self.root)
        self.assertTrue(any("private key" in issue.lower() for issue in issues))
        self.assertTrue(any("device identifier" in issue.lower() for issue in issues))

    def test_allows_small_source_file(self):
        self._stage("src/example.py", b"print('synthetic')\n")
        self.assertEqual(scan_index(self.root), [])

    def test_empty_index_does_not_pass_as_reviewed(self):
        self.assertIn("empty", " ".join(scan_index(self.root)))


if __name__ == "__main__":
    unittest.main()
