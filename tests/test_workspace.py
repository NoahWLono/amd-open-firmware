import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from amd_fw.workspace import WorkspaceError, clean_target_builds


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace"
        self.target = self.workspace / "builds" / "pcengines-apu2"

    def tearDown(self):
        self.temp.cleanup()

    def _create_owned_target(self):
        self.target.mkdir(parents=True)
        marker = {
            "schema_version": 1,
            "owner": "amd-fw-building",
            "target": "pcengines-apu2",
        }
        (self.target / ".amd-fw-build-root.json").write_text(
            json.dumps(marker), encoding="utf-8"
        )
        (self.target / "build.log").write_text("synthetic output", encoding="utf-8")

    def test_removes_only_marked_target_builds(self):
        self._create_owned_target()
        source = self.workspace / "sources" / "coreboot"
        source.mkdir(parents=True)
        (source / "keep.txt").write_text("keep", encoding="utf-8")
        result = clean_target_builds(self.workspace, "pcengines-apu2")
        self.assertEqual(result["status"], "removed")
        self.assertFalse(self.target.exists())
        self.assertTrue((source / "keep.txt").exists())

    def test_refuses_wrong_marker(self):
        self._create_owned_target()
        marker = self.target / ".amd-fw-build-root.json"
        marker.write_text(json.dumps({"owner": "someone-else"}), encoding="utf-8")
        with self.assertRaises(WorkspaceError):
            clean_target_builds(self.workspace, "pcengines-apu2")
        self.assertTrue(self.target.exists())

    def test_refuses_symlink_escape_and_path_like_target(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "keep.txt").write_text("keep", encoding="utf-8")
        (self.workspace / "builds").mkdir(parents=True)
        self.target.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(WorkspaceError):
            clean_target_builds(self.workspace, "pcengines-apu2")
        with self.assertRaises(WorkspaceError):
            clean_target_builds(self.workspace, "../outside")
        self.assertTrue((outside / "keep.txt").exists())


if __name__ == "__main__":
    unittest.main()
