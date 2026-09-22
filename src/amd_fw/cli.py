"""Human and JSON command line interface with stable exit codes."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .catalog import CatalogError, find_target, load_catalog


EXIT_OK = 0
EXIT_USAGE = 2
EXIT_UNSUPPORTED = 3
EXIT_MISSING = 4
EXIT_INTEGRITY = 5
EXIT_OPERATION = 6


class UnsupportedTarget(ValueError):
    pass


class OperationError(ValueError):
    def __init__(self, kind: str, message: str, log_path: str | None = None):
        super().__init__(message)
        self.kind = kind
        self.log_path = log_path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="amd-fw", description="Offline AMD firmware research and pinned builds"
    )
    parser.add_argument("--json", action="store_true", help="emit structured JSON")
    parser.add_argument(
        "--catalog-dir",
        type=Path,
        default=os.environ.get("AMD_FW_CATALOG"),
        help="catalog data directory",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path.home() / ".local" / "state" / "amd-fw",
        help="private state and build workspace",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser(
        "doctor", help="inspect host development tools, not firmware hardware"
    )

    catalog = sub.add_parser(
        "catalog", help="inspect the evidence-backed target catalog"
    )
    cat_sub = catalog.add_subparsers(dest="catalog_command", required=True)
    cat_sub.add_parser("list")
    show = cat_sub.add_parser("show")
    show.add_argument("target")
    cat_sub.add_parser("validate")
    cat_sub.add_parser("export")

    survey = sub.add_parser("survey", help="offline import and private reports")
    survey_sub = survey.add_subparsers(dest="survey_command", required=True)
    survey_import = survey_sub.add_parser("import")
    survey_import.add_argument("source", type=Path)
    survey_report = survey_sub.add_parser("report")
    survey_report.add_argument("survey_id")
    public = survey_sub.add_parser("public-export")
    public.add_argument("survey_id")
    public.add_argument(
        "--reviewed",
        action="store_true",
        help="assert preview and publication rights were reviewed",
    )
    public.add_argument(
        "--output", type=Path, help="write reviewed allowlist JSON as a new local file"
    )

    firmware = sub.add_parser(
        "firmware", help="inspect a supplied firmware package offline"
    )
    firmware_sub = firmware.add_subparsers(dest="firmware_command", required=True)
    inspect = firmware_sub.add_parser("inspect")
    inspect.add_argument("path", type=Path)

    sources = sub.add_parser(
        "sources", help="explicitly fetch and verify pinned upstream inputs"
    )
    sources_sub = sources.add_subparsers(dest="sources_command", required=True)
    fetch = sources_sub.add_parser("fetch")
    fetch.add_argument("target")
    fetch.add_argument(
        "--accept-restricted-license",
        action="store_true",
        help="confirm local use of listed restricted inputs",
    )
    verify = sources_sub.add_parser("verify")
    verify.add_argument("target")

    build = sub.add_parser(
        "build", help="build an exact board target from verified local inputs"
    )
    build.add_argument("target")
    build.add_argument("--jobs", type=int, default=2)
    build.add_argument(
        "--timeout", type=int, default=1200, help="build timeout in seconds"
    )
    reproduce = sub.add_parser("reproduce", help="compare two clean local builds")
    reproduce.add_argument("target")
    reproduce.add_argument("--jobs", type=int, default=2)
    reproduce.add_argument("--timeout", type=int, default=1200)

    artifacts = sub.add_parser("artifacts", help="inspect or verify a local artifact")
    artifact_sub = artifacts.add_subparsers(dest="artifact_command", required=True)
    artifact_inspect = artifact_sub.add_parser("inspect")
    artifact_inspect.add_argument("path", type=Path)
    artifact_verify = artifact_sub.add_parser("verify")
    artifact_verify.add_argument("manifest", type=Path)

    report = sub.add_parser(
        "report", help="show separated catalog, recipe, and validation evidence"
    )
    report.add_argument("target")

    workspace = sub.add_parser(
        "workspace", help="manage project-owned local build outputs"
    )
    workspace_sub = workspace.add_subparsers(dest="workspace_command", required=True)
    clean = workspace_sub.add_parser(
        "clean", help="remove one marked target build directory"
    )
    clean.add_argument("target")

    return parser


def _emit(result: dict[str, Any], json_mode: bool) -> None:
    if json_mode:
        print(json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False))
        return
    if "message" in result:
        print(result["message"])
    elif "targets" in result and isinstance(result["targets"], list):
        for row in result["targets"]:
            print(f"{row['id']}\t{row['kind']}\t{row['name']}")
    elif "target" in result and "recipe" not in result:
        print(
            json.dumps(result["target"], sort_keys=True, indent=2, ensure_ascii=False)
        )
    else:
        print(json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False))


def _doctor() -> dict[str, Any]:
    return {
        "status": "ok",
        "version": __version__,
        "hardware_access": "not_performed",
        "tools": {
            "python": sys.version.split()[0],
            "git": shutil.which("git"),
            "make": shutil.which("make"),
            "gcc": shutil.which("gcc"),
            "bwrap": shutil.which("bwrap"),
            "fish_optional": shutil.which("fish"),
            "qemu_optional": shutil.which("qemu-system-x86_64"),
        },
    }


def _dispatch(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "doctor":
        return _doctor()
    if args.command == "survey":
        from .offline import public_export, survey_import, survey_report

        if args.survey_command == "import":
            return survey_import(args.source, args.workspace)
        if args.survey_command == "report":
            return survey_report(args.survey_id, args.workspace)
        if args.output is not None and not args.reviewed:
            raise ValueError("--output requires --reviewed after examining the preview")
        return public_export(
            args.survey_id,
            args.workspace,
            reviewed=args.reviewed,
            destination=args.output,
        )
    if args.command == "firmware":
        from .offline import firmware_inspect

        return firmware_inspect(args.path)
    if args.command == "workspace":
        from .workspace import WorkspaceError, clean_target_builds

        try:
            return clean_target_builds(args.workspace, args.target)
        except WorkspaceError as exc:
            raise OperationError("invalid_workspace", str(exc)) from exc
    if args.command in {"sources", "build", "reproduce", "artifacts"}:
        from .building import (
            BuildError,
            build_target,
            fetch_sources,
            inspect_artifact,
            reproduce_target,
            verify_artifact,
            verify_sources,
        )

        try:
            if args.command == "sources":
                if args.sources_command == "fetch":
                    return fetch_sources(
                        args.target,
                        args.workspace,
                        accept_restricted_license=args.accept_restricted_license,
                    )
                return verify_sources(args.target, args.workspace)
            if args.command == "build":
                if args.jobs < 1 or args.timeout < 1:
                    raise ValueError("--jobs and --timeout must be positive")
                return build_target(
                    args.target,
                    args.workspace,
                    jobs=args.jobs,
                    timeout_seconds=args.timeout,
                )
            if args.command == "reproduce":
                if args.jobs < 1 or args.timeout < 1:
                    raise ValueError("--jobs and --timeout must be positive")
                return reproduce_target(
                    args.target,
                    args.workspace,
                    jobs=args.jobs,
                    timeout_seconds=args.timeout,
                )
            if args.artifact_command == "inspect":
                return inspect_artifact(args.path)
            return verify_artifact(args.manifest)
        except BuildError as exc:
            raise OperationError(exc.kind, str(exc), exc.log_path) from exc
    targets, evidence = load_catalog(args.catalog_dir)
    if args.command == "report":
        target = find_target(targets, args.target)
        if target is None:
            raise UnsupportedTarget(f"Unknown target: {args.target}")
        recipe = None
        recipe_id = (target.get("build") or {}).get("recipe_id")
        if recipe_id:
            from .building import BuildError, load_recipe_by_id

            try:
                recipe = load_recipe_by_id(recipe_id)
            except BuildError as exc:
                raise OperationError(exc.kind, str(exc), exc.log_path) from exc
        return {
            "status": "ok",
            "target": target,
            "recipe": recipe,
            "evidence": [
                row
                for row in evidence["evidence"]
                if row["id"] in target["evidence_refs"]
            ],
        }
    if args.catalog_command == "validate":
        return {
            "status": "ok",
            "message": f"Catalog valid: {len(targets['targets'])} targets, {len(evidence['evidence'])} evidence records",
            "target_count": len(targets["targets"]),
            "evidence_count": len(evidence["evidence"]),
        }
    if args.catalog_command == "list":
        return {"status": "ok", "targets": targets["targets"]}
    if args.catalog_command == "show":
        target = find_target(targets, args.target)
        if target is None:
            raise UnsupportedTarget(f"Unknown target: {args.target}")
        related = [
            row for row in evidence["evidence"] if row["id"] in target["evidence_refs"]
        ]
        return {"status": "ok", "target": target, "evidence": related}
    if args.catalog_command == "export":
        return {"status": "ok", "catalog": targets, "evidence": evidence}
    raise AssertionError("unreachable command")


def _emit_error(
    code: str, detail: str, exit_code: int, json_mode: bool, log_path: str | None = None
) -> int:
    if json_mode:
        result: dict[str, Any] = {
            "status": "error",
            "error": {"code": code, "detail": detail},
        }
        if log_path is not None:
            result["log_path"] = log_path
        _emit(result, True)
    else:
        print(detail, file=sys.stderr)
    return exit_code


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = _dispatch(args)
    except UnsupportedTarget as exc:
        return _emit_error("unsupported", str(exc), EXIT_UNSUPPORTED, args.json)
    except CatalogError as exc:
        return _emit_error("invalid_catalog", str(exc), EXIT_INTEGRITY, args.json)
    except OperationError as exc:
        exit_code = {
            "unsupported": EXIT_UNSUPPORTED,
            "missing_dependency": EXIT_MISSING,
            "missing_inputs": EXIT_MISSING,
            "license_decision_required": EXIT_MISSING,
            "source_mismatch": EXIT_INTEGRITY,
            "invalid_artifact": EXIT_INTEGRITY,
            "invalid_recipe": EXIT_INTEGRITY,
            "invalid_workspace": EXIT_INTEGRITY,
        }.get(exc.kind, EXIT_OPERATION)
        return _emit_error(exc.kind, str(exc), exit_code, args.json, exc.log_path)
    except ValueError as exc:
        return _emit_error("invalid_argument", str(exc), EXIT_USAGE, args.json)
    if result.get("status") in {"rejected", "error"}:
        if args.json:
            _emit(result, True)
        else:
            print(
                result.get("error", {}).get("detail", "operation failed"),
                file=sys.stderr,
            )
        return EXIT_USAGE if result["status"] == "rejected" else EXIT_OPERATION
    _emit(result, args.json)
    return EXIT_OK
