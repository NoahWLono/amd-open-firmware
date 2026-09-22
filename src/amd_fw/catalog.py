"""Versioned catalog loading and conservative claim validation."""

from __future__ import annotations

import json
import re
from importlib import resources
from pathlib import Path
from typing import Any


class CatalogError(ValueError):
    """A catalog cannot be loaded or contains invalid claims."""


_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_RECIPE_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_KINDS = {"cpu_family", "soc", "board", "research_case"}
_BUILD_STATUSES = {
    "cataloged",
    "research-only",
    "historical-cataloged",
    "historical-target-identified",
    "upstream-target-identified",
    "recipe-implemented",
    "inputs-missing",
    "build-failed",
    "build-verified",
}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        if path.stat().st_size > 4 * 1024 * 1024:
            raise CatalogError(f"Catalog file exceeds 4 MiB limit: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise CatalogError(f"Cannot read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise CatalogError(f"{path} must contain a JSON object")
    return data


def load_catalog(
    root: Path | str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load packaged data, or an explicit directory for validation/tests."""
    base = (
        Path(root)
        if root is not None
        else Path(str(resources.files("amd_fw").joinpath("data")))
    )
    targets = _read_json(base / "targets.json")
    evidence = _read_json(base / "evidence.json")
    recipe_ids = {path.stem for path in (base / "recipes").glob("*.json")}
    issues = validate_catalog(targets, evidence, recipe_ids=recipe_ids)
    if issues:
        raise CatalogError("; ".join(issues))
    from .building import BuildError, _check_recipe

    for row in targets["targets"]:
        recipe_id = (row.get("build") or {}).get("recipe_id")
        if recipe_id is None:
            continue
        recipe = _read_json(base / "recipes" / f"{recipe_id}.json")
        try:
            _check_recipe(recipe, recipe_id)
        except (BuildError, TypeError, AttributeError, KeyError, ValueError) as exc:
            raise CatalogError(f"Invalid recipe {recipe_id}: {exc}") from exc
        upstream = row["upstream"]
        if recipe["board_symbol"] != upstream["kconfig_symbol"]:
            raise CatalogError(f"Recipe {recipe_id} board symbol differs from catalog")
        if recipe["coreboot"]["commit"] != upstream["commit"]:
            raise CatalogError(f"Recipe {recipe_id} commit differs from catalog")
        if (
            recipe["coreboot"].get("board_path")
            != f"src/mainboard/{upstream['mainboard']}"
        ):
            raise CatalogError(f"Recipe {recipe_id} board path differs from catalog")
        source_commit = row["build"].get("source_commit")
        if source_commit is not None and source_commit != upstream["commit"]:
            raise CatalogError(f"Recipe {recipe_id} source commit differs from catalog")
    return targets, evidence


def validate_catalog(
    targets: Any, evidence: Any, recipe_ids: set[str] | None = None
) -> list[str]:
    """Return all detected schema and support-claim errors."""
    issues: list[str] = []
    if not isinstance(targets, dict) or targets.get("schema_version") != 1:
        issues.append("targets schema_version must be 1")
        return issues
    if not isinstance(evidence, dict) or evidence.get("schema_version") != 1:
        issues.append("evidence schema_version must be 1")
        return issues
    target_rows, evidence_rows = targets.get("targets"), evidence.get("evidence")
    if not isinstance(target_rows, list) or not isinstance(evidence_rows, list):
        return ["targets and evidence must be arrays"]

    evidence_ids: set[str] = set()
    for index, row in enumerate(evidence_rows):
        if not isinstance(row, dict):
            issues.append(f"evidence[{index}] must be an object")
            continue
        ident = row.get("id")
        if not isinstance(ident, str) or not _ID.fullmatch(ident):
            issues.append(f"evidence[{index}].id invalid")
        elif ident in evidence_ids:
            issues.append(f"duplicate evidence id {ident}")
        else:
            evidence_ids.add(ident)
        for field in (
            "url",
            "location",
            "retrieved_on",
            "asserts",
            "does_not_establish",
        ):
            if not isinstance(row.get(field), str) or not row[field].strip():
                issues.append(f"evidence[{index}].{field} required")
        if isinstance(row.get("url"), str) and not row["url"].startswith("https://"):
            issues.append(f"evidence[{index}].url must use https")

    target_ids: set[str] = set()
    for index, row in enumerate(target_rows):
        if not isinstance(row, dict):
            issues.append(f"targets[{index}] must be an object")
            continue
        ident = row.get("id")
        prefix = f"targets[{index}]"
        if not isinstance(ident, str) or not _ID.fullmatch(ident):
            issues.append(f"{prefix}.id invalid")
        elif ident in target_ids:
            issues.append(f"duplicate target id {ident}")
        else:
            target_ids.add(ident)
        kind = row.get("kind")
        if not isinstance(kind, str) or kind not in _KINDS:
            issues.append(f"{prefix}.kind must be one of {sorted(_KINDS)}")
        for field in ("name", "manufacturer", "architecture", "cpu_vendor"):
            if not isinstance(row.get(field), str) or not row[field].strip():
                issues.append(f"{prefix}.{field} required")
        refs = row.get("evidence_refs")
        if not isinstance(refs, list) or not refs:
            issues.append(f"{prefix}.evidence_refs required")
        else:
            for ref in refs:
                if not isinstance(ref, str) or ref not in evidence_ids:
                    issues.append(f"{prefix} unresolved evidence {ref}")
        upstream = row.get("upstream") or {}
        build = row.get("build") or {}
        if not isinstance(upstream, dict) or not isinstance(build, dict):
            issues.append(f"{prefix}.upstream and build must be objects")
            continue
        validation = row.get("validation") or {}
        recipe_id = build.get("recipe_id")
        build_status = build.get("status")
        if not isinstance(build_status, str) or build_status not in _BUILD_STATUSES:
            issues.append(f"{prefix}.build.status invalid")
        if not isinstance(build.get("supported"), bool):
            issues.append(f"{prefix}.build.supported must be boolean")
        if recipe_id is not None and (
            not isinstance(recipe_id, str) or not _RECIPE_ID.fullmatch(recipe_id)
        ):
            issues.append(f"{prefix}.build.recipe_id invalid")
        advanced_status = isinstance(build_status, str) and build_status in {
            "recipe-implemented",
            "inputs-missing",
            "build-failed",
            "build-verified",
        }
        if (
            isinstance(build.get("supported"), bool)
            and build["supported"] != advanced_status
        ):
            issues.append(f"{prefix}.build.supported conflicts with readiness status")
        project_build_passed = (
            isinstance(validation, dict) and validation.get("project_build") == "passed"
        )
        has_build_claim = (
            bool(recipe_id)
            or build.get("supported") is True
            or advanced_status
            or project_build_passed
        )
        if has_build_claim:
            if row.get("kind") != "board":
                issues.append(f"{prefix} build recipe requires exact board kind")
            if (
                not isinstance(upstream.get("mainboard"), str)
                or "/" not in upstream["mainboard"]
            ):
                issues.append(f"{prefix}.upstream.mainboard required for build")
            if not isinstance(upstream.get("kconfig_symbol"), str) or not upstream[
                "kconfig_symbol"
            ].startswith("BOARD_"):
                issues.append(f"{prefix}.upstream.kconfig_symbol required for build")
            if not isinstance(upstream.get("commit"), str) or not _COMMIT.fullmatch(
                upstream["commit"]
            ):
                issues.append(
                    f"{prefix}.upstream.commit must be a pinned 40-character SHA"
                )
        if (
            build.get("supported") is True or advanced_status or project_build_passed
        ) and not isinstance(recipe_id, str):
            issues.append(
                f"{prefix}.build.recipe_id required for claimed build support"
            )
        if (
            isinstance(recipe_id, str)
            and recipe_ids is not None
            and recipe_id not in recipe_ids
        ):
            issues.append(f"{prefix}.build.recipe_id missing recipe file: {recipe_id}")
        if build_status == "build-verified" and not project_build_passed:
            issues.append(
                f"{prefix}.validation.project_build must be passed for build-verified"
            )
        if project_build_passed and build_status != "build-verified":
            issues.append(
                f"{prefix}.build.status must be build-verified when project_build passed"
            )
        if build_status == "build-verified":
            digest = (
                validation.get("artifact_sha256")
                if isinstance(validation, dict)
                else None
            )
            size = (
                validation.get("artifact_size_bytes")
                if isinstance(validation, dict)
                else None
            )
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                issues.append(
                    f"{prefix}.validation.artifact_sha256 required for build-verified"
                )
            if not isinstance(size, int) or size <= 0:
                issues.append(
                    f"{prefix}.validation.artifact_size_bytes required for build-verified"
                )
        if row.get("kind") == "research_case" and build.get("recipe_id"):
            issues.append(f"{prefix} research case cannot have a build recipe")
        if not isinstance(validation, dict):
            issues.append(f"{prefix}.validation must be an object")
        elif validation.get("hardware") not in (
            None,
            "not_performed",
            "external",
            "project",
        ):
            issues.append(f"{prefix}.validation.hardware invalid")
        elif (
            validation.get("hardware") in ("external", "project")
            and row.get("kind") != "board"
        ):
            issues.append(f"{prefix}.validation.hardware requires exact board kind")
    kinds_by_id = {
        row["id"]: row["kind"]
        for row in target_rows
        if isinstance(row, dict)
        and isinstance(row.get("id"), str)
        and isinstance(row.get("kind"), str)
    }
    for index, row in enumerate(target_rows):
        if not isinstance(row, dict):
            continue
        relationships = row.get("relationships") or {}
        if not isinstance(relationships, dict):
            issues.append(f"targets[{index}].relationships must be an object")
            continue
        soc_ids = relationships.get("soc_ids", [])
        if not isinstance(soc_ids, list):
            issues.append(f"targets[{index}].relationships.soc_ids must be an array")
            continue
        for soc_id in soc_ids:
            if not isinstance(soc_id, str) or kinds_by_id.get(soc_id) != "soc":
                issues.append(f"targets[{index}] unresolved SoC relationship {soc_id}")
    return issues


def find_target(targets: dict[str, Any], target_id: str) -> dict[str, Any] | None:
    return next((row for row in targets["targets"] if row["id"] == target_id), None)
