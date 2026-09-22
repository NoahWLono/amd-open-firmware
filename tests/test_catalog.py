import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from amd_fw.catalog import CatalogError, load_catalog, validate_catalog


EVIDENCE = {
    "schema_version": 1,
    "evidence": [
        {
            "id": "e1",
            "url": "https://example.org/source",
            "location": "file:10",
            "retrieved_on": "2026-09-22",
            "asserts": "An exact board target exists",
            "does_not_establish": "A physical boot",
        }
    ],
}
TARGETS = {
    "schema_version": 1,
    "targets": [
        {
            "id": "test-board",
            "kind": "board",
            "name": "Synthetic board",
            "manufacturer": "Synthetic",
            "architecture": "x86_64",
            "cpu_vendor": "AMD",
            "evidence_refs": ["e1"],
            "upstream": {
                "project": "coreboot",
                "mainboard": "synthetic/board",
                "kconfig_symbol": "BOARD_SYNTHETIC",
                "commit": "a" * 40,
            },
            "build": {
                "supported": False,
                "status": "upstream-target-identified",
                "recipe_id": None,
            },
            "validation": {"hardware": "not_performed"},
        }
    ],
}


class CatalogTests(unittest.TestCase):
    def test_valid_exact_board(self):
        self.assertEqual(validate_catalog(TARGETS, EVIDENCE), [])

    def test_rejects_unsupported_schema(self):
        bad = copy.deepcopy(TARGETS)
        bad["schema_version"] = 2
        self.assertIn("schema_version", " ".join(validate_catalog(bad, EVIDENCE)))

    def test_rejects_unresolved_evidence(self):
        bad = copy.deepcopy(TARGETS)
        bad["targets"][0]["evidence_refs"] = ["missing"]
        self.assertIn("missing", " ".join(validate_catalog(bad, EVIDENCE)))

    def test_rejects_build_claim_without_exact_board_commit(self):
        bad = copy.deepcopy(TARGETS)
        bad["targets"][0]["build"] = {
            "supported": True,
            "status": "recipe-implemented",
            "recipe_id": "synthetic-recipe",
        }
        del bad["targets"][0]["upstream"]["commit"]
        self.assertIn("commit", " ".join(validate_catalog(bad, EVIDENCE)))

    def test_rejects_build_claim_without_board_symbol(self):
        bad = copy.deepcopy(TARGETS)
        bad["targets"][0]["build"] = {
            "supported": True,
            "status": "recipe-implemented",
            "recipe_id": "synthetic-recipe",
        }
        del bad["targets"][0]["upstream"]["kconfig_symbol"]
        self.assertIn("kconfig_symbol", " ".join(validate_catalog(bad, EVIDENCE)))

    def test_rejects_verified_build_state_on_non_board(self):
        bad = copy.deepcopy(TARGETS)
        bad["targets"][0]["kind"] = "cpu_family"
        bad["targets"][0]["build"] = {
            "supported": False,
            "status": "build-verified",
            "recipe_id": None,
        }
        bad["targets"][0]["validation"]["project_build"] = "passed"
        issues = " ".join(validate_catalog(bad, EVIDENCE))
        self.assertIn("board", issues)
        self.assertIn("recipe", issues)

    def test_rejects_missing_recipe_reference(self):
        bad = copy.deepcopy(TARGETS)
        bad["targets"][0]["build"] = {
            "supported": True,
            "status": "recipe-implemented",
            "recipe_id": "synthetic-recipe",
        }
        self.assertIn(
            "synthetic-recipe",
            " ".join(validate_catalog(bad, EVIDENCE, recipe_ids=set())),
        )

    def test_validates_recipe_reference_when_present(self):
        good = copy.deepcopy(TARGETS)
        good["targets"][0]["build"] = {
            "supported": True,
            "status": "recipe-implemented",
            "recipe_id": "synthetic-recipe",
        }
        self.assertEqual(
            validate_catalog(good, EVIDENCE, recipe_ids={"synthetic-recipe"}), []
        )

    def test_rejects_malformed_build_status_without_crash(self):
        bad = copy.deepcopy(TARGETS)
        bad["targets"][0]["build"]["status"] = ["build-verified"]
        self.assertIn("build.status", " ".join(validate_catalog(bad, EVIDENCE)))

    def test_rejects_unknown_readiness_and_nonboolean_support(self):
        bad = copy.deepcopy(TARGETS)
        bad["targets"][0]["build"]["status"] = "universal-amd-support"
        bad["targets"][0]["build"]["supported"] = "yes"
        issues = " ".join(validate_catalog(bad, EVIDENCE))
        self.assertIn("build.status", issues)
        self.assertIn("build.supported", issues)

    def test_rejects_invalid_recipe_identifier(self):
        bad = copy.deepcopy(TARGETS)
        bad["targets"][0]["build"]["recipe_id"] = "../another-board"
        self.assertIn("recipe_id", " ".join(validate_catalog(bad, EVIDENCE)))

    def test_verified_build_requires_artifact_identity(self):
        bad = copy.deepcopy(TARGETS)
        bad["targets"][0]["build"] = {
            "supported": True,
            "status": "build-verified",
            "recipe_id": "synthetic-recipe",
        }
        bad["targets"][0]["validation"]["project_build"] = "passed"
        issues = " ".join(
            validate_catalog(bad, EVIDENCE, recipe_ids={"synthetic-recipe"})
        )
        self.assertIn("artifact_sha256", issues)
        self.assertIn("artifact_size_bytes", issues)

    def test_rejects_contradictory_recipe_support_and_readiness(self):
        bad = copy.deepcopy(TARGETS)
        bad["targets"][0]["build"] = {
            "supported": True,
            "status": "cataloged",
            "recipe_id": "synthetic-recipe",
        }
        self.assertIn("supported", " ".join(validate_catalog(bad, EVIDENCE)))

        bad["targets"][0]["build"]["supported"] = False
        bad["targets"][0]["build"]["status"] = "build-verified"
        bad["targets"][0]["validation"].update(
            {
                "project_build": "passed",
                "artifact_sha256": "a" * 64,
                "artifact_size_bytes": 1024,
            }
        )
        self.assertIn("supported", " ".join(validate_catalog(bad, EVIDENCE)))

    def test_rejects_unhashable_evidence_reference_without_crash(self):
        bad = copy.deepcopy(TARGETS)
        bad["targets"][0]["evidence_refs"] = [{"not": "an id"}]
        self.assertIn("evidence", " ".join(validate_catalog(bad, EVIDENCE)))

    def test_rejects_unhashable_kind_without_crash(self):
        bad = copy.deepcopy(TARGETS)
        bad["targets"][0]["kind"] = ["board"]
        self.assertIn("kind", " ".join(validate_catalog(bad, EVIDENCE)))

    def test_rejects_unresolved_soc_relationship(self):
        bad = copy.deepcopy(TARGETS)
        bad["targets"][0]["relationships"] = {"soc_ids": ["missing-soc"]}
        self.assertIn("missing-soc", " ".join(validate_catalog(bad, EVIDENCE)))

    def test_load_catalog_rejects_bad_json(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "targets.json").write_text("{broken", encoding="utf-8")
            (root / "evidence.json").write_text(json.dumps(EVIDENCE), encoding="utf-8")
            with self.assertRaises(CatalogError):
                load_catalog(root)

    def test_load_catalog_parses_referenced_recipe_and_checks_board_coherence(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            recipe_dir = root / "recipes"
            recipe_dir.mkdir()
            targets = copy.deepcopy(TARGETS)
            targets["targets"][0]["build"] = {
                "supported": True,
                "status": "recipe-implemented",
                "recipe_id": "synthetic-recipe",
            }
            (root / "targets.json").write_text(json.dumps(targets), encoding="utf-8")
            (root / "evidence.json").write_text(json.dumps(EVIDENCE), encoding="utf-8")
            recipe_file = recipe_dir / "synthetic-recipe.json"
            recipe_file.write_text("{broken", encoding="utf-8")
            with self.assertRaises(CatalogError):
                load_catalog(root)

            source_recipe = (
                Path(__file__).resolve().parents[1]
                / "src/amd_fw/data/recipes/pcengines-apu2.json"
            )
            recipe = json.loads(source_recipe.read_text(encoding="utf-8"))
            recipe["id"] = "synthetic-recipe"
            recipe_file.write_text(json.dumps(recipe), encoding="utf-8")
            with self.assertRaisesRegex(CatalogError, "board symbol|commit|board path"):
                load_catalog(root)


if __name__ == "__main__":
    unittest.main()
