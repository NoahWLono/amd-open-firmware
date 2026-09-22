import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.test_catalog import EVIDENCE, TARGETS


ROOT = Path(__file__).resolve().parents[1]


def run_cli(catalog_dir: Path | None, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    if catalog_dir is not None:
        env["AMD_FW_CATALOG"] = str(catalog_dir)
    else:
        env.pop("AMD_FW_CATALOG", None)
    return subprocess.run(
        [sys.executable, "-m", "amd_fw", *args],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
        check=False,
    )


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="amd fw catalog ")
        self.root = Path(self.temp.name)
        (self.root / "targets.json").write_text(json.dumps(TARGETS), encoding="utf-8")
        (self.root / "evidence.json").write_text(json.dumps(EVIDENCE), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_list_json_contains_exact_board(self):
        result = run_cli(self.root, "--json", "catalog", "list")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["targets"][0]["id"], "test-board")

    def test_show_unknown_target_has_unsupported_exit(self):
        result = run_cli(self.root, "catalog", "show", "unknown")
        self.assertEqual(result.returncode, 3)
        self.assertIn("unknown", result.stderr)

    def test_catalog_validate_rejects_missing_evidence(self):
        (self.root / "evidence.json").write_text(
            '{"schema_version":1,"evidence":[]}', encoding="utf-8"
        )
        result = run_cli(self.root, "catalog", "validate")
        self.assertEqual(result.returncode, 5)
        self.assertIn("unresolved evidence", result.stderr)

    def test_doctor_is_environment_only(self):
        result = run_cli(self.root, "--json", "doctor")
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertIn("python", report["tools"])
        self.assertIn("bwrap", report["tools"])
        self.assertEqual(report["hardware_access"], "not_performed")

    def test_survey_import_report_and_public_preview_with_spaced_paths(self):
        source = self.root / "synthetic survey ü"
        (source / "dmi").mkdir(parents=True)
        (source / "dmi" / "board_name").write_text("SYNTH-BOARD\n", encoding="utf-8")
        workspace = self.root / "private workspace"
        imported = run_cli(
            self.root,
            "--json",
            "--workspace",
            str(workspace),
            "survey",
            "import",
            str(source),
        )
        self.assertEqual(imported.returncode, 0, imported.stderr)
        survey_id = json.loads(imported.stdout)["survey_id"]
        report = run_cli(
            self.root,
            "--json",
            "--workspace",
            str(workspace),
            "survey",
            "report",
            survey_id,
        )
        self.assertEqual(report.returncode, 0, report.stderr)
        self.assertEqual(
            json.loads(report.stdout)["technical_fields"]["board_name"], "SYNTH-BOARD"
        )
        preview = run_cli(
            self.root,
            "--json",
            "--workspace",
            str(workspace),
            "survey",
            "public-export",
            survey_id,
        )
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertEqual(json.loads(preview.stdout)["status"], "review_required")

    def test_firmware_inspect_unknown_format_is_opaque(self):
        firmware = self.root / "vendor update.bin"
        firmware.write_bytes(b"synthetic opaque input")
        result = run_cli(self.root, "--json", "firmware", "inspect", str(firmware))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["format"], "opaque")

    def test_rejected_firmware_input_uses_stderr_and_usage_exit(self):
        link = self.root / "linked input"
        link.symlink_to(self.root / "absent")
        result = run_cli(self.root, "firmware", "inspect", str(link))
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("non-symlink", result.stderr)

    def test_unknown_build_target_has_unsupported_exit(self):
        workspace = self.root / "new workspace"
        result = run_cli(
            self.root, "--workspace", str(workspace), "build", "no-such-board"
        )
        self.assertEqual(result.returncode, 3)
        self.assertFalse(workspace.exists())

    def test_source_verify_does_not_fetch_missing_inputs(self):
        workspace = self.root / "empty workspace"
        result = run_cli(
            self.root,
            "--workspace",
            str(workspace),
            "sources",
            "verify",
            "pcengines-apu2",
        )
        self.assertEqual(result.returncode, 4)
        self.assertFalse(workspace.exists())

    def test_json_build_errors_preserve_kind_and_exit_code(self):
        unsupported = run_cli(self.root, "--json", "build", "no-such-board")
        self.assertEqual(unsupported.returncode, 3)
        self.assertEqual(json.loads(unsupported.stdout)["error"]["code"], "unsupported")
        workspace = self.root / "missing sources"
        missing = run_cli(
            self.root,
            "--json",
            "--workspace",
            str(workspace),
            "sources",
            "verify",
            "pcengines-apu2",
        )
        self.assertEqual(missing.returncode, 4)
        self.assertEqual(json.loads(missing.stdout)["error"]["code"], "missing_inputs")

    def test_report_keeps_build_and_hardware_results_separate(self):
        result = run_cli(None, "--json", "report", "pcengines-apu2")
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["target"]["kind"], "board")
        self.assertEqual(report["target"]["validation"]["hardware"], "not_performed")

    def test_workspace_clean_requires_project_marker(self):
        workspace = self.root / "private workspace"
        target = workspace / "builds" / "pcengines-apu2"
        target.mkdir(parents=True)
        (target / "unrelated.txt").write_text("keep", encoding="utf-8")
        rejected = run_cli(
            self.root,
            "--workspace",
            str(workspace),
            "workspace",
            "clean",
            "pcengines-apu2",
        )
        self.assertEqual(rejected.returncode, 5)
        self.assertTrue((target / "unrelated.txt").exists())
        (target / ".amd-fw-build-root.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "owner": "amd-fw-building",
                    "target": "pcengines-apu2",
                }
            ),
            encoding="utf-8",
        )
        removed = run_cli(
            self.root,
            "--json",
            "--workspace",
            str(workspace),
            "workspace",
            "clean",
            "pcengines-apu2",
        )
        self.assertEqual(removed.returncode, 0, removed.stderr)
        self.assertEqual(json.loads(removed.stdout)["status"], "removed")
        self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
