"""Fail closed on private archives, firmware binaries, and obvious identifiers."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


MAX_SOURCE_BYTES = 2_000_000
DENIED_SUFFIXES = (
    ".rom",
    ".fd",
    ".cap",
    ".bin",
    ".tar",
    ".tar.gz",
    ".tgz",
    ".zip",
    ".img",
    ".iso",
    ".efi",
    ".log",
)
IDENTIFIER = re.compile(
    r"(?im)^\s*(?:Serial Number|System UUID|Product UUID|MAC Address)\s*:\s*\S+"
)
SECRET = re.compile(
    rb"-----BEGIN (?:[A-Z ]* )?PRIVATE KEY-----|\b(?:ghp_|gho_|github_pat_)[A-Za-z0-9_]{20,}|\bAKIA[0-9A-Z]{16}\b"
)


def _git(root: Path, *args: str) -> bytes:
    proc = subprocess.run(
        ["git", "-C", str(root), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=20,
    )
    if proc.returncode:
        raise RuntimeError(proc.stderr.decode("utf-8", "replace").strip())
    return proc.stdout


def scan_index(root: Path | str) -> list[str]:
    """Inspect the exact staged blobs; Git ignore rules cannot protect these."""
    root = Path(root)
    issues: list[str] = []
    records = [
        record
        for record in _git(root, "ls-files", "--stage", "-z").split(b"\0")
        if record
    ]
    if not records:
        return ["empty Git index: no tracked content was reviewed"]
    for record in records:
        meta, raw_path = record.split(b"\t", 1)
        mode, sha, stage = meta.split(b" ")
        if stage != b"0":
            issues.append(f"unmerged staged path: {raw_path!r}")
            continue
        name = raw_path.decode("utf-8", "surrogateescape")
        lower = name.lower()
        if lower.endswith(DENIED_SUFFIXES) or any(
            piece in lower.split("/")
            for piece in ("private", "raw-surveys", "vendor-firmware")
        ):
            issues.append(f"forbidden staged path: {name!r}")
            continue
        if mode == b"120000":
            issues.append(f"symlink requires review: {name!r}")
            continue
        size = int(_git(root, "cat-file", "-s", sha.decode()).strip())
        if size > MAX_SOURCE_BYTES:
            issues.append(f"oversized staged file: {name!r} ({size} bytes)")
            continue
        blob = _git(root, "cat-file", "blob", sha.decode())
        if b"\0" in blob:
            issues.append(f"binary staged content: {name!r}")
            continue
        if SECRET.search(blob):
            issues.append(f"possible private key or credential: {name!r}")
        text = blob.decode("utf-8", "replace")
        if IDENTIFIER.search(text):
            issues.append(f"possible device identifier: {name!r}")
    return issues


def main() -> int:
    try:
        issues = scan_index(Path.cwd())
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"staged scan failed: {exc}", file=sys.stderr)
        return 2
    if issues:
        for issue in issues:
            print(issue, file=sys.stderr)
        return 1
    print("Staged content check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
