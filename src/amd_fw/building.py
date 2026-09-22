"""Pinned coreboot source acquisition and network-isolated AMD board builds.

This module never touches firmware hardware. A successful build proves only that
the configured source and inputs produced a structurally inspectable ROM.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import time
import uuid
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path
from typing import Any, Callable


MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
MAX_LOG_BYTES = 16 * 1024 * 1024
MIN_FREE_BYTES = 2 * 1024 * 1024 * 1024
SOURCE_TIMEOUT = 300
RECIPE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
SHA1 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class BuildError(RuntimeError):
    """Expected build workflow failure with a stable machine-readable kind."""

    def __init__(self, kind: str, message: str, log_path: Path | None = None):
        super().__init__(message)
        self.kind = kind
        self.log_path = str(log_path) if log_path else None


def _safe_relative(value: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise BuildError("invalid_recipe", f"Unsafe recipe path: {value!r}")
    path = Path(value)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in ("", ".", "..") for part in value.split("/"))
    ):
        raise BuildError("invalid_recipe", f"Unsafe recipe path: {value!r}")
    return path


def _guard_workspace_path(workspace: Path, *parts: str) -> Path:
    """Join an owned workspace path without following descendant symlinks."""

    path = workspace
    for value in parts:
        for segment in _safe_relative(value).parts:
            path = path / segment
            if path.is_symlink():
                raise BuildError(
                    "source_mismatch", f"Refusing symlinked workspace path: {path}"
                )
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check_recipe(recipe: dict[str, Any], target_id: str) -> None:
    if (
        not isinstance(recipe, dict)
        or recipe.get("schema_version") != 1
        or recipe.get("id") != target_id
    ):
        raise BuildError("invalid_recipe", f"Invalid recipe identity for {target_id}")
    if (
        recipe.get("publication_eligible") is not False
        or recipe.get("hardware_tested") is not False
    ):
        raise BuildError(
            "invalid_recipe", "Recipes cannot claim publication or hardware validation"
        )
    board_symbol = recipe.get("board_symbol")
    if not isinstance(board_symbol, str) or not re.fullmatch(
        r"BOARD_[A-Z0-9_]+", board_symbol
    ):
        raise BuildError("invalid_recipe", "Recipe lacks an exact board Kconfig symbol")
    submodules = recipe.get("submodules")
    required_files = recipe.get("required_files")
    defconfig = recipe.get("defconfig")
    license_documents = recipe.get("restricted_license_documents")
    cbfs_entries = recipe.get("expected_cbfs_entries")
    embedded_regions = recipe.get("expected_embedded_regions", [])
    for name, value in (
        ("submodules", submodules),
        ("required_files", required_files),
        ("defconfig", defconfig),
        ("restricted_license_documents", license_documents),
        ("expected_cbfs_entries", cbfs_entries),
        ("expected_embedded_regions", embedded_regions),
    ):
        if not isinstance(value, list):
            raise BuildError("invalid_recipe", f"{name} must be a list")
    sources = [recipe.get("coreboot"), recipe.get("seabios"), *submodules]
    for source in sources:
        if not isinstance(source, dict):
            raise BuildError("invalid_recipe", "Each source lock must be an object")
        commit = source.get("commit")
        url = source.get("url")
        if (
            not isinstance(commit, str)
            or not SHA1.fullmatch(commit)
            or not isinstance(url, str)
            or not url.startswith("https://")
        ):
            raise BuildError(
                "invalid_recipe", "Source requires an exact commit and HTTPS URL"
            )
        if "path" in source:
            _safe_relative(source["path"])
    for module in submodules:
        if not isinstance(module.get("license"), str) or not module["license"]:
            raise BuildError("invalid_recipe", "Submodule needs license metadata")
        _safe_relative(module.get("path"))
    for item in required_files:
        if not isinstance(item, dict):
            raise BuildError("invalid_recipe", "Each required input must be an object")
        _safe_relative(item.get("path", ""))
        digest = item.get("sha256")
        if not isinstance(digest, str) or not SHA256.fullmatch(digest):
            raise BuildError("invalid_recipe", "Required input needs a SHA-256 digest")
        if (
            not isinstance(item.get("role"), str)
            or not item["role"]
            or not isinstance(item.get("license"), str)
            or not item["license"]
            or item.get("openness")
            not in (
                "binary_only_restricted",
                "binary_only_redistributable",
            )
        ):
            raise BuildError(
                "invalid_recipe", "Required input needs role and licensing metadata"
            )
    for item in license_documents:
        _safe_relative(item)
    for line in defconfig:
        if not isinstance(line, str) or not re.fullmatch(
            r'CONFIG_[A-Z0-9_]+=(?:y|n|"[^"\n]*")', line
        ):
            raise BuildError("invalid_recipe", "Invalid Kconfig assignment")
    size = recipe.get("expected_rom_size")
    if (
        isinstance(size, bool)
        or not isinstance(size, int)
        or not 1024 <= size <= MAX_ARTIFACT_BYTES
    ):
        raise BuildError("invalid_recipe", "Invalid expected ROM size")
    for entry in cbfs_entries:
        if not isinstance(entry, str) or not entry or any(c.isspace() for c in entry):
            raise BuildError("invalid_recipe", "Invalid expected CBFS entry")
    for region in embedded_regions:
        if not isinstance(region, dict):
            raise BuildError("invalid_recipe", "Embedded region must be an object")
        offset = region.get("offset")
        length = region.get("size")
        if (
            not isinstance(region.get("name"), str)
            or not region["name"]
            or isinstance(offset, bool)
            or not isinstance(offset, int)
            or isinstance(length, bool)
            or not isinstance(length, int)
            or offset < 0
            or length <= 0
            or offset + length > size
        ):
            raise BuildError("invalid_recipe", "Invalid embedded region bounds")
        _safe_relative(region.get("source_path"))


def load_recipe_by_id(target_id: str) -> dict[str, Any]:
    """Load one bundled, reviewed recipe; arbitrary filenames are never accepted."""

    if not RECIPE_ID.fullmatch(target_id):
        raise BuildError("unsupported", f"Unknown build target: {target_id}")
    resource = resources.files("amd_fw").joinpath(
        "data", "recipes", f"{target_id}.json"
    )
    if not resource.is_file():
        raise BuildError("unsupported", f"No build recipe for target: {target_id}")
    try:
        recipe = json.loads(resource.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BuildError(
            "invalid_recipe", f"Could not load recipe {target_id}: {exc}"
        ) from exc
    if not isinstance(recipe, dict):
        raise BuildError("invalid_recipe", "Recipe root must be an object")
    _check_recipe(recipe, target_id)
    return recipe


def _existing_parent(path: Path) -> Path:
    parent = path
    while not parent.exists():
        parent = parent.parent
    return parent


def _require_space(workspace: Path) -> None:
    if shutil.disk_usage(_existing_parent(workspace)).free < MIN_FREE_BYTES:
        raise BuildError(
            "missing_dependency", "At least 2 GiB of free workspace disk is required"
        )


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )


def _build_file_io(action: Callable[[], Any], log_path: Path, description: str) -> Any:
    """Give expected local I/O failures a stable build error and retain context."""

    try:
        return action()
    except (OSError, UnicodeError) as exc:
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as stream:
                stream.write(f"{description}: {exc}\n")
        except OSError:
            pass
        raise BuildError("build_failed", f"{description}: {exc}", log_path) from exc


def _owned_directory(path: Path, marker_name: str, marker: dict[str, Any]) -> None:
    if path.is_symlink():
        raise BuildError(
            "source_mismatch", f"Refusing symlinked workspace directory: {path}"
        )
    if path.exists():
        marker_path = path / marker_name
        if not marker_path.is_file():
            raise BuildError(
                "source_mismatch", f"Existing directory lacks ownership marker: {path}"
            )
        try:
            existing = json.loads(marker_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise BuildError(
                "source_mismatch", f"Invalid ownership marker: {marker_path}"
            ) from exc
        if existing != marker:
            raise BuildError(
                "source_mismatch", f"Ownership marker mismatch: {marker_path}"
            )
    else:
        path.mkdir(parents=True)
        _write_json(path / marker_name, marker)


def _run_logged(
    argv: list[str],
    *,
    cwd: Path,
    log_path: Path,
    timeout_seconds: int,
    kind: str,
    env: dict[str, str] | None = None,
) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    child_env = os.environ.copy()
    child_env.update(
        {
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
        }
    )
    if env:
        child_env.update(env)
    with log_path.open("ab") as log:
        log.write(("\n$ " + " ".join(argv) + "\n").encode("utf-8", errors="replace"))
        log.flush()
        try:
            process = subprocess.Popen(
                argv,
                cwd=cwd,
                env=child_env,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except OSError as exc:
            raise BuildError(
                "missing_dependency", f"Could not launch {argv[0]}: {exc}", log_path
            ) from exc
        deadline = time.monotonic() + timeout_seconds
        while (return_code := process.poll()) is None:
            if time.monotonic() >= deadline or log_path.stat().st_size > MAX_LOG_BYTES:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                reason = (
                    "timed out"
                    if time.monotonic() >= deadline
                    else "exceeded log limit"
                )
                raise BuildError(
                    "timeout", f"Command {reason}; see {log_path}", log_path
                )
            time.sleep(0.2)
    if return_code != 0:
        tail = log_path.read_bytes()[-4096:].decode("utf-8", errors="replace")
        raise BuildError(
            kind, f"Command failed ({return_code}); see {log_path}\n{tail}", log_path
        )


def _git_output(path: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(path), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
        check=False,
        env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull},
    )
    if result.returncode:
        raise BuildError(
            "source_mismatch",
            f"Git verification failed at {path}: {result.stderr.strip()}",
        )
    return result.stdout.strip()


def _verify_git(path: Path, commit: str, url: str) -> None:
    if not path.is_dir() or path.is_symlink():
        raise BuildError("missing_inputs", f"Missing source checkout: {path}")
    if _git_output(path, "rev-parse", "HEAD") != commit:
        raise BuildError(
            "source_mismatch", f"Wrong commit in {path}; expected {commit}"
        )
    if _git_output(path, "remote", "get-url", "origin") != url:
        raise BuildError(
            "source_mismatch", f"Wrong source URL in {path}; expected {url}"
        )
    if _git_output(path, "status", "--porcelain=v1", "--untracked-files=no"):
        raise BuildError(
            "source_mismatch", f"Tracked source files were modified in {path}"
        )


def verify_sources(target_id: str, workspace: str | Path) -> dict[str, Any]:
    """Verify exact Git commits and selected binary checksums offline."""

    recipe = load_recipe_by_id(target_id)
    workspace_path = Path(workspace).expanduser().resolve()
    source = _guard_workspace_path(workspace_path, "sources", "coreboot")
    _verify_git(source, recipe["coreboot"]["commit"], recipe["coreboot"]["url"])
    for module in recipe["submodules"]:
        _verify_git(
            _guard_workspace_path(
                workspace_path, "sources", "coreboot", module["path"]
            ),
            module["commit"],
            module["url"],
        )
    seabios = _guard_workspace_path(
        workspace_path,
        "sources",
        "coreboot",
        "payloads",
        "external",
        "SeaBIOS",
        "seabios",
    )
    _verify_git(seabios, recipe["seabios"]["commit"], recipe["seabios"]["url"])
    hashes: dict[str, str] = {}
    for item in recipe["required_files"]:
        path = _guard_workspace_path(
            workspace_path, "sources", "coreboot", item["path"]
        )
        if not path.is_file() or path.is_symlink():
            raise BuildError("missing_inputs", f"Missing required binary input: {path}")
        actual = _sha256(path)
        if actual != item["sha256"]:
            raise BuildError(
                "source_mismatch", f"Checksum mismatch for {path}: {actual}"
            )
        hashes[item["path"]] = actual
    for relative in recipe["restricted_license_documents"]:
        path = _guard_workspace_path(workspace_path, "sources", "coreboot", relative)
        if not path.is_file() or path.is_symlink():
            raise BuildError("missing_inputs", f"Missing license document: {path}")
        hashes[relative] = _sha256(path)
    return {
        "status": "verified",
        "target": target_id,
        "source_path": str(source),
        "coreboot_commit": recipe["coreboot"]["commit"],
        "submodule_commits": {
            item["path"]: item["commit"] for item in recipe["submodules"]
        },
        "seabios_commit": recipe["seabios"]["commit"],
        "input_hashes": hashes,
    }


def fetch_sources(
    target_id: str,
    workspace: str | Path,
    *,
    accept_restricted_license: bool = False,
) -> dict[str, Any]:
    """Fetch only reviewed, pinned upstream inputs after a license decision."""

    recipe = load_recipe_by_id(target_id)
    if not accept_restricted_license:
        raise BuildError(
            "license_decision_required",
            "This recipe needs proprietary binary inputs. Review its bundled license documents "
            "and pass an explicit restricted-license decision before fetching.",
        )
    if shutil.which("git") is None:
        raise BuildError("missing_dependency", "git is required for source acquisition")
    workspace_path = Path(workspace).expanduser().resolve()
    _require_space(workspace_path)
    sources = _guard_workspace_path(workspace_path, "sources")
    _owned_directory(
        sources,
        ".amd-fw-sources.json",
        {"schema_version": 1, "owner": "amd-fw-building"},
    )
    checkout = _guard_workspace_path(workspace_path, "sources", "coreboot")
    log_path = sources / "fetch.log"
    if not checkout.exists():
        checkout.mkdir()
        _run_logged(
            ["git", "-c", "init.defaultBranch=master", "init", str(checkout)],
            cwd=sources,
            log_path=log_path,
            timeout_seconds=30,
            kind="fetch_failed",
        )
    if checkout.is_symlink() or not (checkout / ".git").exists():
        raise BuildError(
            "source_mismatch",
            f"Existing source is not an owned Git checkout: {checkout}",
        )
    try:
        origin = _git_output(checkout, "remote", "get-url", "origin")
    except BuildError:
        origin = None
    if origin is None:
        _run_logged(
            [
                "git",
                "-C",
                str(checkout),
                "remote",
                "add",
                "origin",
                recipe["coreboot"]["url"],
            ],
            cwd=sources,
            log_path=log_path,
            timeout_seconds=30,
            kind="fetch_failed",
        )
    elif origin != recipe["coreboot"]["url"]:
        raise BuildError("source_mismatch", f"Wrong source URL in {checkout}: {origin}")
    try:
        head = _git_output(checkout, "rev-parse", "HEAD")
    except BuildError:
        head = None
    if head is None:
        _run_logged(
            [
                "git",
                "-C",
                str(checkout),
                "fetch",
                "--depth=1",
                "origin",
                recipe["coreboot"]["commit"],
            ],
            cwd=sources,
            log_path=log_path,
            timeout_seconds=SOURCE_TIMEOUT,
            kind="fetch_failed",
        )
        _run_logged(
            [
                "git",
                "-C",
                str(checkout),
                "checkout",
                "--detach",
                recipe["coreboot"]["commit"],
            ],
            cwd=sources,
            log_path=log_path,
            timeout_seconds=60,
            kind="fetch_failed",
        )
    elif head != recipe["coreboot"]["commit"]:
        raise BuildError(
            "source_mismatch", f"Wrong coreboot commit in {checkout}: {head}"
        )
    _verify_git(checkout, recipe["coreboot"]["commit"], recipe["coreboot"]["url"])
    for item in recipe["submodules"]:
        _run_logged(
            [
                "git",
                "-C",
                str(checkout),
                "-c",
                f"submodule.{item['path']}.update=checkout",
                "submodule",
                "update",
                "--init",
                "--depth",
                "1",
                item["path"],
            ],
            cwd=sources,
            log_path=log_path,
            timeout_seconds=SOURCE_TIMEOUT,
            kind="fetch_failed",
        )
    seabios = _guard_workspace_path(
        workspace_path,
        "sources",
        "coreboot",
        "payloads",
        "external",
        "SeaBIOS",
        "seabios",
    )
    if not seabios.exists():
        seabios.mkdir(parents=True)
        _run_logged(
            ["git", "-c", "init.defaultBranch=master", "init", str(seabios)],
            cwd=sources,
            log_path=log_path,
            timeout_seconds=30,
            kind="fetch_failed",
        )
    if seabios.is_symlink() or not (seabios / ".git").exists():
        raise BuildError(
            "source_mismatch",
            f"Existing SeaBIOS source is not a Git checkout: {seabios}",
        )
    try:
        seabios_origin = _git_output(seabios, "remote", "get-url", "origin")
    except BuildError:
        seabios_origin = None
    if seabios_origin is None:
        _run_logged(
            [
                "git",
                "-C",
                str(seabios),
                "remote",
                "add",
                "origin",
                recipe["seabios"]["url"],
            ],
            cwd=sources,
            log_path=log_path,
            timeout_seconds=30,
            kind="fetch_failed",
        )
    elif seabios_origin != recipe["seabios"]["url"]:
        raise BuildError(
            "source_mismatch", f"Wrong SeaBIOS URL in {seabios}: {seabios_origin}"
        )
    try:
        seabios_head = _git_output(seabios, "rev-parse", "HEAD")
    except BuildError:
        seabios_head = None
    if seabios_head is None:
        _run_logged(
            [
                "git",
                "-C",
                str(seabios),
                "fetch",
                "--depth=1",
                "origin",
                recipe["seabios"]["commit"],
            ],
            cwd=sources,
            log_path=log_path,
            timeout_seconds=SOURCE_TIMEOUT,
            kind="fetch_failed",
        )
        _run_logged(
            [
                "git",
                "-C",
                str(seabios),
                "checkout",
                "-B",
                "master",
                recipe["seabios"]["commit"],
            ],
            cwd=sources,
            log_path=log_path,
            timeout_seconds=30,
            kind="fetch_failed",
        )
    elif seabios_head != recipe["seabios"]["commit"]:
        raise BuildError(
            "source_mismatch", f"Wrong SeaBIOS commit in {seabios}: {seabios_head}"
        )
    result = verify_sources(target_id, workspace_path)
    decisions = _guard_workspace_path(workspace_path, "sources", "decisions")
    decisions.mkdir(exist_ok=True)
    receipt = decisions / f"{target_id}.json"
    _write_json(
        receipt,
        {
            "schema_version": 1,
            "acknowledged_by_operator_flag": True,
            "target": target_id,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return {
        **result,
        "status": "fetched",
        "log_path": str(log_path),
        "license_decision_path": str(receipt),
    }


def inspect_artifact(path: str | Path) -> dict[str, Any]:
    """Bounded structural inspection of one local ROM file, without execution."""

    artifact = Path(path).expanduser().resolve()
    if not artifact.is_file():
        raise BuildError(
            "invalid_artifact", f"Artifact is not a regular file: {artifact}"
        )
    size = artifact.stat().st_size
    if not 0 < size <= MAX_ARTIFACT_BYTES:
        raise BuildError(
            "invalid_artifact",
            f"Artifact size is outside the 64 MiB inspection bound: {size}",
        )
    content = artifact.read_bytes()
    fmap_offset = content.find(b"__FMAP__")
    cbfs_offset = content.find(b"LARCHIVE")
    return {
        "status": "inspected",
        "path": str(artifact),
        "size": size,
        "sha256": hashlib.sha256(content).hexdigest(),
        "format": "coreboot_structure_candidate"
        if fmap_offset >= 0 and cbfs_offset >= 0
        else "unrecognized",
        "signature_offsets": {"fmap": fmap_offset, "cbfs": cbfs_offset},
        "validation_scope": "size, hash, and structural signatures only; no boot or signature verification",
    }


def verify_artifact(manifest_path: str | Path) -> dict[str, Any]:
    """Check a private build manifest against its artifact bytes offline."""

    manifest_file = Path(manifest_path).expanduser().resolve()
    if not manifest_file.is_file() or manifest_file.stat().st_size > 1024 * 1024:
        raise BuildError(
            "invalid_artifact", f"Missing or oversized manifest: {manifest_file}"
        )
    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BuildError(
            "invalid_artifact", f"Invalid manifest: {manifest_file}"
        ) from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise BuildError("invalid_artifact", "Unsupported artifact manifest schema")
    if (
        manifest.get("publication_eligible") is not False
        or manifest.get("hardware_tested") is not False
    ):
        raise BuildError(
            "invalid_artifact",
            "Manifest cannot assert publication or hardware validation",
        )
    record = manifest.get("artifact")
    if not isinstance(record, dict):
        raise BuildError("invalid_artifact", "Manifest lacks an artifact record")
    try:
        relative = _safe_relative(record.get("path", ""))
    except BuildError as exc:
        raise BuildError("invalid_artifact", str(exc)) from exc
    artifact = manifest_file.parent / relative
    if artifact.is_symlink() or not artifact.resolve().is_relative_to(
        manifest_file.parent
    ):
        raise BuildError(
            "invalid_artifact", "Artifact path escapes the manifest directory"
        )
    inspected = inspect_artifact(artifact)
    if inspected["size"] != record.get("size") or inspected["sha256"] != record.get(
        "sha256"
    ):
        raise BuildError(
            "invalid_artifact", f"Artifact digest or size mismatch: {artifact}"
        )
    if inspected["format"] != "coreboot_structure_candidate":
        raise BuildError(
            "invalid_artifact", f"Coreboot structure signatures are missing: {artifact}"
        )
    return {
        "status": "verified",
        "target": manifest.get("target"),
        "manifest_path": str(manifest_file),
        "artifact": inspected,
        "publication_eligible": False,
        "hardware_tested": False,
    }


def _bwrap_command(run_dir: Path, command: list[str]) -> list[str]:
    executable = shutil.which("bwrap")
    if executable is None:
        raise BuildError(
            "missing_dependency",
            "bubblewrap (bwrap) is required for network-isolated builds",
        )
    return [
        executable,
        "--unshare-net",
        "--die-with-parent",
        "--ro-bind",
        "/usr",
        "/usr",
        "--symlink",
        "usr/bin",
        "/bin",
        "--symlink",
        "usr/lib",
        "/lib",
        "--symlink",
        "usr/lib",
        "/lib64",
        "--ro-bind",
        "/etc",
        "/etc",
        "--dev",
        "/dev",
        "--proc",
        "/proc",
        "--tmpfs",
        "/tmp",
        "--bind",
        str(run_dir),
        "/workspace",
        "--chdir",
        "/workspace/coreboot",
        "--setenv",
        "HOME",
        "/tmp",
        "--setenv",
        "TMPDIR",
        "/tmp",
        "--setenv",
        "PATH",
        "/usr/bin:/bin",
        "--setenv",
        "LC_ALL",
        "C",
        "--setenv",
        "TZ",
        "UTC",
        "--setenv",
        "GIT_CONFIG_GLOBAL",
        "/dev/null",
        *command,
    ]


def _tool_versions() -> dict[str, str]:
    commands = {
        "gcc": ["gcc", "--version"],
        "make": ["make", "--version"],
        "git": ["git", "--version"],
        "bwrap": ["bwrap", "--version"],
        "iasl": ["iasl", "-v"],
        "ld": ["ld", "--version"],
        "as": ["as", "--version"],
        "bison": ["bison", "--version"],
        "flex": ["flex", "--version"],
        "python3": ["python3", "--version"],
    }
    versions = {}
    for name, argv in commands.items():
        if shutil.which(argv[0]) is None:
            raise BuildError(
                "missing_dependency", f"Required build tool is missing: {name}"
            )
        result = subprocess.run(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=20,
            check=False,
        )
        if result.returncode:
            raise BuildError(
                "missing_dependency", f"Could not identify build tool: {name}"
            )
        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        versions[name] = (
            next((line for line in lines if "version" in line.lower()), "unknown")
            if name == "iasl"
            else (lines[0] if lines else "unknown")
        )
    return versions


def load_toolchain_lock() -> dict[str, Any]:
    """Read the measured host executable lock shipped with the recipes."""

    path = resources.files("amd_fw").joinpath("data", "toolchain-lock.json")
    try:
        lock = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BuildError("invalid_recipe", "Missing or invalid toolchain lock") from exc
    if (
        not isinstance(lock, dict)
        or lock.get("schema_version") != 1
        or not isinstance(lock.get("versions"), dict)
    ):
        raise BuildError("invalid_recipe", "Unsupported toolchain lock")
    return lock


def verify_toolchain_lock(actual: dict[str, str] | None = None) -> dict[str, Any]:
    """Refuse builds if a locked host executable version drifted."""

    lock = load_toolchain_lock()
    versions = _tool_versions() if actual is None else actual
    drift = {
        name: {"expected": expected, "actual": versions.get(name)}
        for name, expected in lock["versions"].items()
        if versions.get(name) != expected
    }
    if drift:
        raise BuildError(
            "missing_dependency",
            f"Host toolchain differs from {lock['profile']}: {json.dumps(drift, sort_keys=True)}",
        )
    return {
        "status": "verified",
        "profile": lock["profile"],
        "versions": versions,
        "lock_sha256": hashlib.sha256(
            json.dumps(lock, sort_keys=True).encode("utf-8")
        ).hexdigest(),
    }


def _cbfs_entries(report: str) -> list[str]:
    entries = []
    for line in report.splitlines():
        fields = line.split()
        if (
            len(fields) >= 4
            and fields[1].startswith("0x")
            and fields[0] not in ("Name", "(empty)")
        ):
            entries.append(fields[0])
    return entries


def _verify_build_output(
    recipe: dict[str, Any], checkout: Path, cbfs_report: str
) -> dict[str, Any]:
    rom = checkout / "build" / "coreboot.rom"
    inspected = inspect_artifact(rom)
    if inspected["size"] != recipe["expected_rom_size"]:
        raise BuildError(
            "invalid_artifact", f"Unexpected ROM size: {inspected['size']}"
        )
    if inspected["format"] != "coreboot_structure_candidate":
        raise BuildError(
            "invalid_artifact", "ROM lacks FMAP or CBFS structure signatures"
        )
    entries = _cbfs_entries(cbfs_report)
    missing = set(recipe["expected_cbfs_entries"]) - set(entries)
    if missing:
        raise BuildError(
            "invalid_artifact",
            f"Missing required CBFS entries: {', '.join(sorted(missing))}",
        )
    regions = []
    with rom.open("rb") as image:
        for region in recipe.get("expected_embedded_regions", []):
            source = checkout / _safe_relative(region["source_path"])
            if source.stat().st_size != region["size"]:
                raise BuildError(
                    "invalid_artifact", f"Unexpected {region['name']} source size"
                )
            image.seek(region["offset"])
            actual = image.read(region["size"])
            if actual != source.read_bytes():
                raise BuildError(
                    "invalid_artifact",
                    f"ROM {region['name']} region differs from pinned source",
                )
            regions.append(
                {
                    "name": region["name"],
                    "offset": region["offset"],
                    "size": region["size"],
                    "source_sha256": _sha256(source),
                    "equal_to_source": True,
                }
            )
    return {
        "inspection": inspected,
        "cbfs_entries": entries,
        "embedded_regions": regions,
    }


def _component_inventory(
    recipe: dict[str, Any], input_hashes: dict[str, str]
) -> list[dict[str, Any]]:
    """Describe source and binary inputs without asserting release rights."""

    components = [
        {
            "name": "coreboot",
            "kind": "source_tree",
            "role": "board firmware implementation",
            "url": recipe["coreboot"]["url"],
            "commit": recipe["coreboot"]["commit"],
            "license": "per-file SPDX identifiers in pinned upstream tree",
            "openness": "source_available",
        },
        {
            "name": "SeaBIOS",
            "kind": "source_tree",
            "role": "boot payload",
            "url": recipe["seabios"]["url"],
            "commit": recipe["seabios"]["commit"],
            "license": "GPL-3.0 and LGPL-3.0 upstream license texts; inspect per-file terms",
            "openness": "source_available",
        },
    ]
    for module in recipe["submodules"]:
        components.append(
            {
                "name": module["path"],
                "kind": "upstream_submodule",
                "role": "pinned source or firmware input collection",
                "url": module["url"],
                "commit": module["commit"],
                "license": module["license"],
                "openness": "mixed_or_restricted"
                if "blobs" in module["path"]
                else "source_available",
            }
        )
    for item in recipe["required_files"]:
        components.append(
            {
                "name": item["path"],
                "kind": "binary_input",
                "role": item["role"],
                "sha256": input_hashes[item["path"]],
                "license": item["license"],
                "openness": item["openness"],
                "publication_status": "held_for_review",
            }
        )
    return components


def _clean_build_checkout(
    recipe: dict[str, Any], run_dir: Path, log_path: Path
) -> None:
    """Remove all untracked and ignored files from the disposable source copy."""

    checkout = run_dir / "coreboot"
    seabios = checkout / "payloads" / "external" / "SeaBIOS" / "seabios"
    staged_seabios = run_dir / ".amd-fw-seabios-stage"
    if not seabios.is_dir() or seabios.is_symlink() or staged_seabios.exists():
        raise BuildError("source_mismatch", "Invalid copied SeaBIOS checkout")
    seabios.rename(staged_seabios)
    _run_logged(
        ["git", "-C", str(checkout), "clean", "-ffdx"],
        cwd=run_dir,
        log_path=log_path,
        timeout_seconds=120,
        kind="build_failed",
    )
    seabios.parent.mkdir(parents=True, exist_ok=True)
    staged_seabios.rename(seabios)
    for module in recipe["submodules"]:
        path = checkout / _safe_relative(module["path"])
        _run_logged(
            ["git", "-C", str(path), "clean", "-ffdx"],
            cwd=run_dir,
            log_path=log_path,
            timeout_seconds=120,
            kind="build_failed",
        )
        _verify_git(path, module["commit"], module["url"])
    _run_logged(
        ["git", "-C", str(seabios), "clean", "-ffdx"],
        cwd=run_dir,
        log_path=log_path,
        timeout_seconds=120,
        kind="build_failed",
    )
    _verify_git(checkout, recipe["coreboot"]["commit"], recipe["coreboot"]["url"])
    _verify_git(seabios, recipe["seabios"]["commit"], recipe["seabios"]["url"])
    for item in recipe.get("required_files", []):
        path = checkout / _safe_relative(item["path"])
        if not path.is_file() or path.is_symlink() or _sha256(path) != item["sha256"]:
            raise BuildError(
                "source_mismatch", f"Required input changed in build copy: {path}"
            )


def build_target(
    target_id: str,
    workspace: str | Path,
    *,
    jobs: int = 2,
    timeout_seconds: int = 1200,
) -> dict[str, Any]:
    """Build a pinned board ROM in a disposable, network-isolated bwrap tree."""

    recipe = load_recipe_by_id(target_id)
    if not isinstance(jobs, int) or not 1 <= jobs <= 8:
        raise BuildError("invalid_recipe", "jobs must be between 1 and 8")
    if not isinstance(timeout_seconds, int) or not 60 <= timeout_seconds <= 3600:
        raise BuildError(
            "invalid_recipe", "timeout_seconds must be between 60 and 3600"
        )
    workspace_path = Path(workspace).expanduser().resolve()
    verified_sources = verify_sources(target_id, workspace_path)
    receipt = _guard_workspace_path(
        workspace_path, "sources", "decisions", f"{target_id}.json"
    )
    try:
        decision = json.loads(receipt.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BuildError(
            "license_decision_required",
            f"Missing restricted input decision receipt: {receipt}",
        ) from exc
    if (
        decision.get("target") != target_id
        or decision.get("acknowledged_by_operator_flag") is not True
    ):
        raise BuildError(
            "license_decision_required",
            f"Invalid restricted input decision receipt: {receipt}",
        )
    toolchain_lock = verify_toolchain_lock()
    toolchain = toolchain_lock["versions"]
    _require_space(workspace_path)
    build_root = _guard_workspace_path(workspace_path, "builds", target_id)
    _owned_directory(
        build_root,
        ".amd-fw-build-root.json",
        {"schema_version": 1, "owner": "amd-fw-building", "target": target_id},
    )
    run_id = (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + uuid.uuid4().hex[:8]
    )
    run_dir = build_root / run_id
    run_dir.mkdir()
    checkout = run_dir / "coreboot"
    log_path = run_dir / "build.log"
    _build_file_io(
        lambda: shutil.copytree(
            workspace_path / "sources" / "coreboot", checkout, symlinks=True
        ),
        log_path,
        "Could not copy pinned source into disposable run",
    )
    _build_file_io(
        lambda: _clean_build_checkout(recipe, run_dir, log_path),
        log_path,
        "Could not clean disposable source copy",
    )
    _build_file_io(
        lambda: (run_dir / "defconfig").write_text(
            "\n".join(recipe["defconfig"]) + "\n", encoding="utf-8"
        ),
        log_path,
        "Could not write defconfig",
    )
    _run_logged(
        _bwrap_command(
            run_dir,
            [
                "/usr/bin/make",
                "defconfig",
                "KBUILD_DEFCONFIG=/workspace/defconfig",
                "UPDATED_SUBMODULES=1",
            ],
        ),
        cwd=run_dir,
        log_path=log_path,
        timeout_seconds=min(180, timeout_seconds),
        kind="build_failed",
    )
    config_text = _build_file_io(
        lambda: (checkout / ".config").read_text(encoding="utf-8"),
        log_path,
        "Could not read generated Kconfig",
    )
    for symbol in (recipe["board_symbol"], "PAYLOAD_SEABIOS"):
        if f"CONFIG_{symbol}=y" not in config_text:
            raise BuildError(
                "build_failed", f"Kconfig did not select {symbol}", log_path
            )
    if (
        target_id == "starlabs-starbook-cezanne"
        and "CONFIG_ADD_FSP_BINARIES=y" not in config_text
    ):
        raise BuildError(
            "build_failed", "StarBook build omitted AMD FSP binaries", log_path
        )
    _run_logged(
        _bwrap_command(
            run_dir,
            ["/usr/bin/make", f"-j{jobs}", "BUILD_TIMELESS=1", "UPDATED_SUBMODULES=1"],
        ),
        cwd=run_dir,
        log_path=log_path,
        timeout_seconds=timeout_seconds,
        kind="build_failed",
    )
    cbfs_path = run_dir / "cbfs.txt"
    _run_logged(
        _bwrap_command(
            run_dir,
            [
                "/workspace/coreboot/build/util/cbfstool/cbfstool",
                "/workspace/coreboot/build/coreboot.rom",
                "print",
            ],
        ),
        cwd=run_dir,
        log_path=cbfs_path,
        timeout_seconds=60,
        kind="invalid_artifact",
    )
    cbfs_report = _build_file_io(
        lambda: cbfs_path.read_text(encoding="utf-8"),
        log_path,
        "Could not read CBFS report",
    )
    output = _build_file_io(
        lambda: _verify_build_output(recipe, checkout, cbfs_report),
        log_path,
        "Could not inspect built ROM",
    )
    artifacts = run_dir / "artifacts"
    _build_file_io(artifacts.mkdir, log_path, "Could not create artifact directory")
    artifact = artifacts / "coreboot.rom"
    _build_file_io(
        lambda: shutil.copy2(checkout / "build" / "coreboot.rom", artifact),
        log_path,
        "Could not retain ROM artifact",
    )
    manifest_path = run_dir / "manifest.json"
    manifest = {
        "schema_version": 1,
        "target": target_id,
        "board_symbol": recipe["board_symbol"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "recipe_sha256": _sha256(
            Path(
                resources.files("amd_fw").joinpath(
                    "data", "recipes", f"{target_id}.json"
                )
            )
        ),
        "coreboot_commit": recipe["coreboot"]["commit"],
        "submodule_commits": verified_sources["submodule_commits"],
        "seabios_commit": recipe["seabios"]["commit"],
        "input_hashes": verified_sources["input_hashes"],
        "components": _component_inventory(recipe, verified_sources["input_hashes"]),
        "component_inventory_scope": (
            "Curated source, submodule, and explicitly required binary inputs; not a complete "
            "per-file SBOM. Additional Cezanne PSP files referenced by pinned fw.cfg and "
            "amd_blobs may be incorporated without individual hashes in this manifest."
            if target_id == "starlabs-starbook-cezanne"
            else "Curated source, submodule, and explicitly required binary inputs; not a complete per-file SBOM."
        ),
        "config_sha256": hashlib.sha256(config_text.encode("utf-8")).hexdigest(),
        "toolchain": toolchain,
        "toolchain_lock_profile": toolchain_lock["profile"],
        "toolchain_lock_sha256": toolchain_lock["lock_sha256"],
        "isolation": "bubblewrap user namespace; network namespace unshared; /usr and /etc read-only; synthetic /dev; only run directory writable",
        "input_hygiene": "git clean -ffdx in disposable coreboot, required submodules, and SeaBIOS checkouts before build",
        "build_command": [
            "make",
            f"-j{jobs}",
            "BUILD_TIMELESS=1",
            "UPDATED_SUBMODULES=1",
        ],
        "artifact": {
            "path": "artifacts/coreboot.rom",
            "size": output["inspection"]["size"],
            "sha256": output["inspection"]["sha256"],
        },
        "cbfs_entries": output["cbfs_entries"],
        "embedded_regions": output["embedded_regions"],
        "validation_scope": "build and offline structure only; no physical boot or security validation",
        "publication_eligible": False,
        "hardware_tested": False,
    }
    _build_file_io(
        lambda: _write_json(manifest_path, manifest),
        log_path,
        "Could not write artifact manifest",
    )
    verify_artifact(manifest_path)
    _build_file_io(
        lambda: shutil.rmtree(checkout),
        log_path,
        "Could not remove disposable source copy",
    )
    return {
        "status": "built",
        "target": target_id,
        "validation_status": "build_verified",
        "artifact_path": str(artifact),
        "artifact_sha256": manifest["artifact"]["sha256"],
        "manifest_path": str(manifest_path),
        "build_log_path": str(log_path),
        "cbfs_report_path": str(cbfs_path),
        "publication_eligible": False,
        "hardware_tested": False,
    }


def _first_difference(first: Path, second: Path) -> int | None:
    offset = 0
    with first.open("rb") as left, second.open("rb") as right:
        while True:
            a = left.read(1024 * 1024)
            b = right.read(1024 * 1024)
            if a != b:
                for index, (left_byte, right_byte) in enumerate(zip(a, b)):
                    if left_byte != right_byte:
                        return offset + index
                return offset + min(len(a), len(b))
            if not a:
                return None
            offset += len(a)


def reproduce_target(
    target_id: str,
    workspace: str | Path,
    *,
    jobs: int = 2,
    timeout_seconds: int = 1200,
) -> dict[str, Any]:
    """Build twice in independent trees and compare the exact ROM bytes."""

    first = build_target(
        target_id, workspace, jobs=jobs, timeout_seconds=timeout_seconds
    )
    second = build_target(
        target_id, workspace, jobs=jobs, timeout_seconds=timeout_seconds
    )
    same = first["artifact_sha256"] == second["artifact_sha256"]
    result = {
        "schema_version": 1,
        "status": "reproducible" if same else "mismatch",
        "target": target_id,
        "first_manifest": first["manifest_path"],
        "second_manifest": second["manifest_path"],
        "first_sha256": first["artifact_sha256"],
        "second_sha256": second["artifact_sha256"],
        "first_difference_offset": None
        if same
        else _first_difference(
            Path(first["artifact_path"]), Path(second["artifact_path"])
        ),
        "scope": "same pinned inputs and current host toolchain in two network-isolated build trees",
        "hardware_tested": False,
    }
    path = (
        Path(workspace).expanduser().resolve()
        / "builds"
        / target_id
        / ("reproduce-" + uuid.uuid4().hex[:8] + ".json")
    )
    _write_json(path, result)
    return {**result, "report_path": str(path)}
