"""Narrow cleanup of build directories created by this project."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any


TARGET_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
MARKER = ".amd-fw-build-root.json"


class WorkspaceError(ValueError):
    """Cleanup target is not a verified project-owned build directory."""


def clean_target_builds(workspace: Path, target_id: str) -> dict[str, Any]:
    """Remove exactly one marked target build directory, never shared sources."""

    if not TARGET_ID.fullmatch(target_id):
        raise WorkspaceError("Target must be a simple catalog identifier")

    workspace = Path(workspace).expanduser()
    builds = workspace / "builds"
    target = builds / target_id
    if workspace.is_symlink() or builds.is_symlink() or target.is_symlink():
        raise WorkspaceError("Refusing cleanup through a symbolic link")
    if not target.exists():
        return {"status": "absent", "target": target_id, "path": str(target)}
    if not target.is_dir():
        raise WorkspaceError("Build target path is not a directory")
    if target.resolve().parent != builds.resolve():
        raise WorkspaceError("Build target is outside the build workspace")

    marker = target / MARKER
    if marker.is_symlink() or not marker.is_file():
        raise WorkspaceError("Build target has no regular ownership marker")
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise WorkspaceError("Build ownership marker is unreadable") from exc
    expected = {"owner": "amd-fw-building", "schema_version": 1, "target": target_id}
    if data != expected:
        raise WorkspaceError("Build ownership marker does not match this target")

    shutil.rmtree(target)
    return {"status": "removed", "target": target_id, "path": str(target)}
