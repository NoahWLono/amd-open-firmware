"""Tests for the pinned, offline coreboot build adapter."""

import copy
import hashlib
import importlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def building():
    spec = importlib.util.find_spec("amd_fw.building")
    if spec is None:
        raise AssertionError("amd_fw.building module is missing")
    return importlib.import_module("amd_fw.building")


class BuildingTests(unittest.TestCase):
    def test_real_recipes_pin_distinct_amd_boards_and_sources(self):
        module = building()
        apu2 = module.load_recipe_by_id("pcengines-apu2")
        starbook = module.load_recipe_by_id("starlabs-starbook-cezanne")
        self.assertEqual(apu2["board_symbol"], "BOARD_PCENGINES_APU2")
        self.assertEqual(starbook["board_symbol"], "BOARD_STARLABS_STARBOOK_CEZANNE")
        self.assertEqual(
            apu2["coreboot"]["commit"], "5cbf8afc4c08949c9b4ee1cb9dc5439add8a937e"
        )
        self.assertEqual(apu2["coreboot"]["commit"], starbook["coreboot"]["commit"])
        self.assertNotEqual(apu2["soc"], starbook["soc"])
        for recipe in (apu2, starbook):
            self.assertFalse(recipe["publication_eligible"])
            self.assertFalse(recipe["hardware_tested"])
            self.assertEqual(len(recipe["seabios"]["commit"]), 40)
            self.assertTrue(recipe["required_files"])

    def test_malformed_recipe_fields_fail_as_invalid_recipe(self):
        module = building()
        base = module.load_recipe_by_id("pcengines-apu2")
        cases = (
            ("submodules", "not a list"),
            ("required_files", [None]),
            ("defconfig", None),
            ("expected_cbfs_entries", "AGESA"),
            ("expected_embedded_regions", [{"name": "bad"}]),
            ("coreboot", {"url": "https://example.test", "commit": None}),
        )
        for key, value in cases:
            with self.subTest(key=key):
                recipe = copy.deepcopy(base)
                recipe[key] = value
                with self.assertRaises(module.BuildError) as caught:
                    module._check_recipe(recipe, "pcengines-apu2")
                self.assertEqual(caught.exception.kind, "invalid_recipe")

    def test_reject_unknown_or_path_like_recipe_id(self):
        module = building()
        for target in ("unknown", "../pcengines-apu2", "pcengines-apu2/../../etc"):
            with (
                self.subTest(target=target),
                self.assertRaises(module.BuildError) as caught,
            ):
                module.load_recipe_by_id(target)
            self.assertEqual(caught.exception.kind, "unsupported")

    def test_relative_recipe_paths_reject_root_and_normalized_traversal(self):
        module = building()
        for value in (".", "a/../b", "a//b", "a/", "../x", "/absolute"):
            with self.subTest(value=value), self.assertRaises(module.BuildError):
                module._safe_relative(value)

    def test_restricted_blob_fetch_requires_explicit_decision_before_network(self):
        module = building()
        with tempfile.TemporaryDirectory(prefix="amd fw test ") as td:
            workspace = Path(td)
            with self.assertRaises(module.BuildError) as caught:
                module.fetch_sources("starlabs-starbook-cezanne", workspace)
            self.assertEqual(caught.exception.kind, "license_decision_required")
            self.assertFalse((workspace / "sources").exists())

    def test_artifact_verification_detects_mutation_and_refuses_path_escape(self):
        module = building()
        with tempfile.TemporaryDirectory(prefix="amd fw test ") as td:
            root = Path(td)
            artifact = root / "coreboot.rom"
            artifact.write_bytes(b"__FMAP__" + b"\0" * 80 + b"LARCHIVE")
            inspected = module.inspect_artifact(artifact)
            self.assertEqual(inspected["format"], "coreboot_structure_candidate")
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "target": "synthetic-test",
                        "artifact": {
                            "path": "coreboot.rom",
                            "size": inspected["size"],
                            "sha256": inspected["sha256"],
                        },
                        "publication_eligible": False,
                        "hardware_tested": False,
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(module.verify_artifact(manifest)["status"], "verified")
            artifact.write_bytes(artifact.read_bytes() + b"tampered")
            with self.assertRaises(module.BuildError) as caught:
                module.verify_artifact(manifest)
            self.assertEqual(caught.exception.kind, "invalid_artifact")
            manifest.write_text(
                json.dumps({"schema_version": 1, "artifact": {"path": "../outside"}}),
                encoding="utf-8",
            )
            with self.assertRaises(module.BuildError) as caught:
                module.verify_artifact(manifest)
            self.assertEqual(caught.exception.kind, "invalid_artifact")

    def test_first_difference_reports_earliest_byte_even_with_different_lengths(self):
        module = building()
        with tempfile.TemporaryDirectory() as td:
            left = Path(td) / "left"
            right = Path(td) / "right"
            left.write_bytes(b"abcd")
            right.write_bytes(b"axcde")
            self.assertEqual(module._first_difference(left, right), 1)

    def test_build_file_io_converts_only_filesystem_failures(self):
        module = building()
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "build.log"
            with self.assertRaises(module.BuildError) as caught:
                module._build_file_io(
                    lambda: (_ for _ in ()).throw(PermissionError("denied")),
                    log,
                    "copy checkout",
                )
            self.assertEqual(caught.exception.kind, "build_failed")
            self.assertEqual(caught.exception.log_path, str(log))
            with self.assertRaises(ValueError):
                module._build_file_io(
                    lambda: (_ for _ in ()).throw(ValueError("bug")),
                    log,
                    "copy checkout",
                )

    def test_toolchain_lock_rejects_version_drift(self):
        module = building()
        lock = module.load_toolchain_lock()
        self.assertIn("gcc", lock["versions"])
        drifted = dict(lock["versions"])
        drifted["gcc"] = "synthetic different compiler"
        with self.assertRaises(module.BuildError) as caught:
            module.verify_toolchain_lock(drifted)
        self.assertEqual(caught.exception.kind, "missing_dependency")

    def test_workspace_path_guard_refuses_symlinked_parent(self):
        module = building()
        with tempfile.TemporaryDirectory(prefix="amd fw bounds ") as td:
            workspace = Path(td) / "workspace"
            outside = Path(td) / "outside"
            workspace.mkdir()
            outside.mkdir()
            (workspace / "builds").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(module.BuildError) as caught:
                module._guard_workspace_path(workspace, "builds", "pcengines-apu2")
            self.assertEqual(caught.exception.kind, "source_mismatch")
            self.assertEqual(
                module._guard_workspace_path(workspace, "sources", "decisions"),
                workspace / "sources" / "decisions",
            )

    def test_disposable_copy_excludes_untracked_build_inputs(self):
        module = building()

        def git(path: Path, *args: str) -> str:
            result = subprocess.run(
                ["git", "-C", str(path), *args],
                check=True,
                text=True,
                capture_output=True,
            )
            return result.stdout.strip()

        with tempfile.TemporaryDirectory(prefix="amd fw clean ") as td:
            root = Path(td)
            source = root / "source"
            source.mkdir()
            git(source, "init", "-q")
            (source / "README").write_text("tracked coreboot\n", encoding="utf-8")
            git(source, "add", "README")
            git(
                source,
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.invalid",
                "commit",
                "-qm",
                "fixture",
            )
            coreboot_commit = git(source, "rev-parse", "HEAD")
            git(source, "remote", "add", "origin", str(source))
            (source / "build").mkdir()
            (source / "build" / "stale.o").write_bytes(b"stale")
            seabios = source / "payloads" / "external" / "SeaBIOS" / "seabios"
            seabios.mkdir(parents=True)
            git(seabios, "init", "-q")
            (seabios / "README").write_text("tracked payload\n", encoding="utf-8")
            git(seabios, "add", "README")
            git(
                seabios,
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.invalid",
                "commit",
                "-qm",
                "fixture",
            )
            seabios_commit = git(seabios, "rev-parse", "HEAD")
            git(seabios, "remote", "add", "origin", str(seabios))
            (seabios / "stale.bin").write_bytes(b"stale")
            run = root / "run"
            run.mkdir()
            copy = run / "coreboot"
            shutil.copytree(source, copy, symlinks=True)
            recipe = {
                "coreboot": {"url": str(source), "commit": coreboot_commit},
                "seabios": {"url": str(seabios), "commit": seabios_commit},
                "submodules": [],
            }
            module._clean_build_checkout(recipe, run, run / "build.log")
            self.assertTrue((copy / "README").is_file())
            self.assertTrue(
                (copy / "payloads/external/SeaBIOS/seabios/README").is_file()
            )
            self.assertFalse((copy / "build").exists())
            self.assertFalse(
                (copy / "payloads/external/SeaBIOS/seabios/stale.bin").exists()
            )
            self.assertTrue((source / "build/stale.o").is_file())
            self.assertTrue((seabios / "stale.bin").is_file())
            second_run = root / "second-run"
            second_run.mkdir()
            shutil.copytree(source, second_run / "coreboot", symlinks=True)
            recipe["required_files"] = [
                {
                    "path": "build/stale.o",
                    "sha256": hashlib.sha256(b"stale").hexdigest(),
                }
            ]
            with self.assertRaises(module.BuildError) as caught:
                module._clean_build_checkout(
                    recipe, second_run, second_run / "build.log"
                )
            self.assertEqual(caught.exception.kind, "source_mismatch")

    def test_fetch_resumes_a_partial_git_checkout_without_deleting_it(self):
        module = building()

        def git(*args: str, cwd: Path) -> str:
            result = subprocess.run(
                ["git", *args], cwd=cwd, text=True, capture_output=True, check=True
            )
            return result.stdout.strip()

        with tempfile.TemporaryDirectory(prefix="amd fw recovery ") as td:
            root = Path(td)
            upstream = root / "upstream"
            upstream.mkdir()
            coreboot_work = upstream / "coreboot-work"
            coreboot_work.mkdir()
            git("init", "-q", cwd=coreboot_work)
            (coreboot_work / "README").write_text(
                "synthetic coreboot\n", encoding="utf-8"
            )
            git("add", "README", cwd=coreboot_work)
            git(
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.invalid",
                "commit",
                "-qm",
                "fixture",
                cwd=coreboot_work,
            )
            coreboot_commit = git("rev-parse", "HEAD", cwd=coreboot_work)
            seabios_work = upstream / "seabios-work"
            seabios_work.mkdir()
            git("init", "-q", cwd=seabios_work)
            (seabios_work / "README").write_text(
                "synthetic seabios\n", encoding="utf-8"
            )
            git("add", "README", cwd=seabios_work)
            git(
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.invalid",
                "commit",
                "-qm",
                "fixture",
                cwd=seabios_work,
            )
            seabios_commit = git("rev-parse", "HEAD", cwd=seabios_work)
            workspace = root / "workspace"
            sources = workspace / "sources"
            sources.mkdir(parents=True)
            (sources / ".amd-fw-sources.json").write_text(
                json.dumps({"schema_version": 1, "owner": "amd-fw-building"}),
                encoding="utf-8",
            )
            checkout = sources / "coreboot"
            checkout.mkdir()
            git("init", "-q", cwd=checkout)
            git("remote", "add", "origin", str(coreboot_work), cwd=checkout)
            recipe = {
                "id": "synthetic-test",
                "coreboot": {"url": str(coreboot_work), "commit": coreboot_commit},
                "seabios": {"url": str(seabios_work), "commit": seabios_commit},
                "submodules": [],
                "required_files": [],
                "restricted_license_documents": [],
            }
            with (
                patch.object(module, "load_recipe_by_id", return_value=recipe),
                patch.object(module, "_require_space"),
            ):
                result = module.fetch_sources(
                    "synthetic-test", workspace, accept_restricted_license=True
                )
            self.assertEqual(result["status"], "fetched")
            self.assertEqual(git("rev-parse", "HEAD", cwd=checkout), coreboot_commit)
            self.assertTrue((sources / "fetch.log").is_file())


if __name__ == "__main__":
    unittest.main()
