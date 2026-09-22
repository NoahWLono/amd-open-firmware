"""Bounded offline analysis of supplied surveys and firmware files.

No function here invokes a survey command, extracts an archive, or accesses a
hardware device. Survey reports are private by default. The public form uses
an allowlist and requires an explicit review assertion from its caller.
"""

from __future__ import annotations

import hashlib
import bz2
import gzip
import io
import json
import lzma
import os
from datetime import date, datetime
from pathlib import Path, PurePosixPath
import re
import stat
import struct
import tarfile
import uuid
import zipfile
from typing import BinaryIO


SCHEMA_VERSION = 1
MAX_SURVEY_FILES = 512
MAX_SURVEY_MEMBER = 8 * 1024 * 1024
MAX_SURVEY_EXPANDED = 32 * 1024 * 1024
MAX_SURVEY_ARCHIVE = 64 * 1024 * 1024
MAX_SURVEY_TAR_STREAM = 40 * 1024 * 1024
MAX_ZIP_CENTRAL_DIRECTORY = 2 * 1024 * 1024
MAX_FIRMWARE_ZIP_CENTRAL_DIRECTORY = 4 * 1024 * 1024
MAX_FIRMWARE_FILE = 256 * 1024 * 1024
MAX_FIRMWARE_MEMBERS = 1024
MAX_FIRMWARE_EXPANDED = 512 * 1024 * 1024
MAX_REPORT_FILE = 4 * 1024 * 1024
FMP_CAPSULE_GUID = uuid.UUID("6dcbd5ed-e82d-4c44-bda1-7194199ad92a")
_SURVEY_ID = re.compile(r"^survey-[0-9a-f]{16}$")
_SHA256_LINE = re.compile(r"^([0-9a-fA-F]{64})[ \t]+\*?(.+?)\s*$")
_PCI_ID = re.compile(r"\[([0-9a-fA-F]{4}:[0-9a-fA-F]{4})\]")
_MISSING = re.compile(r"command not found|not installed|not found: command", re.I)
_DENIED = re.compile(r"permission denied|operation not permitted", re.I)
_ERROR = re.compile(r"(^|\s)(error|failed|failure):?($|\s)", re.I)
_PUBLIC_FIELDS = frozenset(
    {
        "board_vendor",
        "board_name",
        "board_version",
        "product_name",
        "product_family",
        "bios_vendor",
        "bios_version",
        "bios_date",
        "cpu_vendor",
        "cpu_model_name",
        "cpu_family",
        "cpu_model",
        "cpu_stepping",
    }
)
_BASENAME_FIELDS = {
    key: key
    for key in (
        "board_vendor",
        "board_name",
        "board_version",
        "product_name",
        "product_family",
        "bios_vendor",
        "bios_version",
        "bios_date",
    )
}


class _Rejected(ValueError):
    """An input violates a documented safety or schema boundary."""


def _failure(status: str, code: str, detail: str) -> dict:
    return {
        "status": status,
        "schema_version": SCHEMA_VERSION,
        "error": {"code": code, "detail": detail},
    }


def _name(raw: str) -> str:
    if not isinstance(raw, str) or not raw or len(raw) > 512:
        raise _Rejected("empty or overlong member name")
    if "\\" in raw or "\x00" in raw or any(ord(char) < 32 for char in raw):
        raise _Rejected("unsafe member name")
    if raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        raise _Rejected("absolute member path")
    parts = raw.rstrip("/").split("/")
    if any(part == ".." for part in parts):
        raise _Rejected("parent-directory traversal")
    parts = [part for part in parts if part not in ("", ".")]
    if not parts or len(parts) > 16:
        raise _Rejected("empty or deeply nested member path")
    return str(PurePosixPath(*parts))


def _check_executable(name: str, data: bytes, mode: int = 0) -> None:
    if mode & 0o111 or data.startswith((b"\x7fELF", b"MZ", b"#!")):
        raise _Rejected("executable survey member")
    if PurePosixPath(name).suffix.lower() in {
        ".exe",
        ".dll",
        ".so",
        ".sh",
        ".py",
        ".bat",
    }:
        raise _Rejected("executable survey member")


def _add(
    items: dict[str, bytes],
    raw_name: str,
    data: bytes,
    declared_size: int,
    mode: int = 0,
) -> None:
    name = _name(raw_name)
    if name in items:
        raise _Rejected("duplicate member path")
    if len(items) >= MAX_SURVEY_FILES:
        raise _Rejected("survey member count limit exceeded")
    if (
        declared_size < 0
        or declared_size > MAX_SURVEY_MEMBER
        or len(data) != declared_size
    ):
        raise _Rejected("survey member size limit or metadata mismatch")
    if sum(map(len, items.values())) + len(data) > MAX_SURVEY_EXPANDED:
        raise _Rejected("survey expanded-size limit exceeded")
    _check_executable(name, data, mode)
    items[name] = data


def _directory_members(source: Path) -> dict[str, bytes]:
    items: dict[str, bytes] = {}
    entry_count = 0
    dir_flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
    file_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)

    def walk(dir_fd: int, prefix: str, depth: int) -> None:
        nonlocal entry_count
        if depth > 16:
            raise _Rejected("survey directory nesting limit exceeded")
        with os.scandir(dir_fd) as entries:
            for entry in entries:
                entry_count += 1
                if entry_count > MAX_SURVEY_FILES:
                    raise _Rejected("survey member count limit exceeded")
                member_name = f"{prefix}/{entry.name}" if prefix else entry.name
                _name(member_name)
                metadata = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(metadata.st_mode):
                    raise _Rejected("survey directory contains a symlink")
                if stat.S_ISDIR(metadata.st_mode):
                    child_fd = os.open(entry.name, dir_flags, dir_fd=dir_fd)
                    try:
                        walk(child_fd, member_name, depth + 1)
                    finally:
                        os.close(child_fd)
                elif stat.S_ISREG(metadata.st_mode):
                    if metadata.st_size > MAX_SURVEY_MEMBER:
                        raise _Rejected("survey member size limit exceeded")
                    fd = os.open(entry.name, file_flags, dir_fd=dir_fd)
                    with os.fdopen(fd, "rb") as stream:
                        data = stream.read(MAX_SURVEY_MEMBER + 1)
                    _add(items, member_name, data, metadata.st_size, metadata.st_mode)
                else:
                    raise _Rejected("survey directory contains a special file")

    root_fd = os.open(source, dir_flags)
    try:
        walk(root_fd, "", 0)
    finally:
        os.close(root_fd)
    return items


def _zip_members(source: Path) -> dict[str, bytes]:
    items: dict[str, bytes] = {}
    _zip_preflight(source)
    with zipfile.ZipFile(source) as archive:
        members = archive.infolist()
        if len(members) > MAX_SURVEY_FILES:
            raise _Rejected("survey member count limit exceeded")
        declared_total = 0
        for info in members:
            name = _name(info.filename)
            mode = (info.external_attr >> 16) & 0xFFFF if info.create_system == 3 else 0
            file_type = stat.S_IFMT(mode)
            if file_type not in (0, stat.S_IFREG, stat.S_IFDIR):
                raise _Rejected("archive contains a link or special file")
            if info.flag_bits & 1:
                raise _Rejected("encrypted survey archive member")
            if info.is_dir():
                continue
            declared_total += info.file_size
            if (
                info.file_size > MAX_SURVEY_MEMBER
                or declared_total > MAX_SURVEY_EXPANDED
                or (info.file_size and info.compress_size == 0)
                or (info.compress_size and info.file_size > info.compress_size * 100)
            ):
                raise _Rejected("survey expansion limit exceeded")
            with archive.open(info) as stream:
                data = stream.read(MAX_SURVEY_MEMBER + 1)
            _add(items, name, data, info.file_size, mode)
    return items


def _zip_preflight(
    source: Path,
    *,
    max_members: int = MAX_SURVEY_FILES,
    max_directory_bytes: int = MAX_ZIP_CENTRAL_DIRECTORY,
) -> None:
    """Bound central-directory allocation before ZipFile constructs ZipInfo objects."""
    with source.open("rb") as stream:
        _zip_preflight_stream(
            stream,
            source.stat().st_size,
            max_members=max_members,
            max_directory_bytes=max_directory_bytes,
        )


def _zip_preflight_stream(
    stream: BinaryIO,
    size: int,
    *,
    max_members: int,
    max_directory_bytes: int,
) -> None:
    original_position = stream.tell()
    try:
        stream.seek(max(0, size - (22 + 65535)))
        tail = stream.read()
    finally:
        stream.seek(original_position)
    signature = b"PK\x05\x06"
    index = tail.rfind(signature)
    while index >= 0:
        if index + 22 <= len(tail):
            (
                _,
                disk,
                directory_disk,
                disk_entries,
                total_entries,
                directory_size,
                directory_offset,
                comment_size,
            ) = struct.unpack_from("<IHHHHIIH", tail, index)
            if index + 22 + comment_size == len(tail):
                if disk != 0 or directory_disk != 0 or disk_entries != total_entries:
                    raise _Rejected("multi-disk ZIP survey is unsupported")
                if total_entries > max_members or total_entries == 0xFFFF:
                    raise _Rejected("archive member count limit exceeded")
                if directory_size > max_directory_bytes or directory_size == 0xFFFFFFFF:
                    raise _Rejected("ZIP central directory metadata limit exceeded")
                if directory_offset + directory_size > size - len(tail) + index:
                    raise _Rejected("ZIP central directory bounds inconsistent")
                return
        index = tail.rfind(signature, 0, index)
    raise _Rejected("ZIP end record missing or unsupported")


def _tar_members(source: Path) -> dict[str, bytes]:
    items: dict[str, bytes] = {}
    declared_total = 0
    entry_count = 0
    with source.open("rb") as raw:
        magic = raw.read(6)
        raw.seek(0)
        if magic.startswith(b"\x1f\x8b"):
            stream = gzip.GzipFile(fileobj=raw)
        elif magic.startswith(b"BZh"):
            stream = bz2.BZ2File(raw)
        elif magic.startswith(b"\xfd7zXZ\x00"):
            stream = lzma.LZMAFile(raw)
        else:
            stream = raw
        try:
            expanded_tar = stream.read(MAX_SURVEY_TAR_STREAM + 1)
        except (OSError, EOFError, lzma.LZMAError) as exc:
            raise _Rejected("unsupported or corrupt tar stream") from exc
        finally:
            if stream is not raw:
                stream.close()
    if len(expanded_tar) > MAX_SURVEY_TAR_STREAM:
        raise _Rejected("tar stream size limit exceeded")
    with tarfile.open(fileobj=io.BytesIO(expanded_tar), mode="r:") as archive:
        for member in archive:
            entry_count += 1
            if entry_count > MAX_SURVEY_FILES:
                raise _Rejected("survey member count limit exceeded")
            name = _name(member.name)
            if member.isdir():
                continue
            if not member.isfile():
                raise _Rejected("archive contains a link or special file")
            declared_total += member.size
            if (
                len(items) >= MAX_SURVEY_FILES
                or member.size > MAX_SURVEY_MEMBER
                or declared_total > MAX_SURVEY_EXPANDED
            ):
                raise _Rejected("survey expansion limit exceeded")
            stream = archive.extractfile(member)
            if stream is None:
                raise _Rejected("unreadable archive member")
            with stream:
                data = stream.read(MAX_SURVEY_MEMBER + 1)
            _add(items, name, data, member.size, member.mode)
    return items


def _survey_members(source: Path) -> tuple[dict[str, bytes], str]:
    if source.is_symlink():
        raise _Rejected("source symlinks are not accepted")
    if source.is_dir():
        return _directory_members(source), "directory"
    if not source.is_file():
        raise _Rejected("source is not a regular file or directory")
    if source.stat().st_size > MAX_SURVEY_ARCHIVE:
        raise _Rejected("survey archive size limit exceeded")
    if zipfile.is_zipfile(source):
        return _zip_members(source), "zip"
    try:
        return _tar_members(source), "tar"
    except tarfile.TarError as exc:
        raise _Rejected("unsupported survey archive format") from exc


def _classify(data: bytes) -> str:
    if not data:
        return "empty"
    if b"\x00" in data:
        return "binary_present_exit_unknown"
    text = data.decode("utf-8", "replace")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    missing = bool(_MISSING.search(text))
    denied = bool(_DENIED.search(text))
    errors = bool(_ERROR.search(text))
    if missing or denied or errors:
        non_error_lines = [
            line
            for line in lines
            if not (
                _MISSING.search(line) or _DENIED.search(line) or _ERROR.search(line)
            )
        ]
        if non_error_lines:
            return "partial_or_error_exit_unknown"
        if missing:
            return "missing_utility"
        if denied:
            return "permission_denied"
        return "error_only"
    return "content_present_exit_unknown"


def _safe_value(value: str) -> str | None:
    value = value.strip()
    if (
        not value
        or len(value) > 128
        or "\x00" in value
        or "\n" in value
        or "\r" in value
        or "/" in value
        or "\\" in value
        or "@" in value
    ):
        return None
    if any(ord(char) < 32 for char in value):
        return None
    return value


def _technical_value(field: str, raw: str) -> str | None:
    if field == "bios_date":
        value = raw.strip()
        try:
            if re.fullmatch(r"\d{2}/\d{2}/\d{4}", value):
                return datetime.strptime(value, "%m/%d/%Y").date().isoformat()
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                return date.fromisoformat(value).isoformat()
        except ValueError:
            pass
        return None
    return _safe_value(raw)


def _technical_fields(
    items: dict[str, bytes],
) -> tuple[dict[str, str], list[str], list[dict]]:
    candidates: dict[str, list[dict]] = {}
    pci_ids: set[str] = set()

    def record(field: str, value: str | None, source: str, priority: int) -> None:
        if not value:
            return
        bucket = candidates.setdefault(field, [])
        if any(item["value"] == value and item["source"] == source for item in bucket):
            return
        if len(bucket) < 16:
            bucket.append({"value": value, "source": source, "priority": priority})

    for name, data in sorted(items.items()):
        if not data or b"\x00" in data or len(data) > 1024 * 1024:
            continue
        text = data.decode("utf-8", "replace")
        basename = PurePosixPath(name).name.lower()
        field = _BASENAME_FIELDS.get(basename)
        if field:
            value = _technical_value(field, text)
            record(field, value, name, 2)
        if basename in {
            "cpuinfo",
            "cpuinfo.txt",
            "lscpu",
            "lscpu.txt",
        } or basename.endswith(("-cpuinfo.txt", "-lscpu.txt", "summary.txt")):
            cpu_map = {
                "vendor_id": "cpu_vendor",
                "vendor id": "cpu_vendor",
                "model name": "cpu_model_name",
                "cpu family": "cpu_family",
                "model": "cpu_model",
                "stepping": "cpu_stepping",
            }
            for line in text.splitlines():
                if ":" not in line:
                    continue
                key, raw = line.split(":", 1)
                field = cpu_map.get(key.strip().lower())
                value = _technical_value(field, raw) if field else None
                if field:
                    record(
                        field, value, name, 1 if basename.endswith("summary.txt") else 2
                    )
                if basename.endswith("summary.txt"):
                    field = key.strip().lower()
                    value = _technical_value(field, raw)
                    if field in _PUBLIC_FIELDS:
                        record(field, value, name, 1)
        if basename in {"dmidecode", "dmidecode.txt"} or basename.endswith(
            "-dmidecode.txt"
        ):
            section = ""
            for line in text.splitlines():
                stripped = line.strip()
                if stripped in {
                    "BIOS Information",
                    "Base Board Information",
                    "System Information",
                }:
                    section = stripped
                    continue
                if not line.startswith((" ", "\t")):
                    section = ""
                    continue
                if ":" not in stripped:
                    continue
                key, raw = stripped.split(":", 1)
                dmi_map = {
                    ("BIOS Information", "Vendor"): "bios_vendor",
                    ("BIOS Information", "Version"): "bios_version",
                    ("BIOS Information", "Release Date"): "bios_date",
                    ("Base Board Information", "Manufacturer"): "board_vendor",
                    ("Base Board Information", "Product Name"): "board_name",
                    ("Base Board Information", "Version"): "board_version",
                    ("System Information", "Product Name"): "product_name",
                    ("System Information", "Family"): "product_family",
                }
                field = dmi_map.get((section, key))
                value = _technical_value(field, raw) if field else None
                if field:
                    record(field, value, name, 2)
        if "lspci" in basename:
            pci_ids.update(
                match.lower() for match in _PCI_ID.findall(text[: 1024 * 1024])
            )
    fields: dict[str, str] = {}
    conflicts: list[dict] = []
    for field, bucket in sorted(candidates.items()):
        ranked = sorted(bucket, key=lambda item: -item["priority"])
        selected = ranked[0]
        fields[field] = selected["value"]
        if len({item["value"] for item in bucket}) > 1:
            conflicts.append(
                {
                    "field": field,
                    "selected_value": selected["value"],
                    "selected_source": selected["source"],
                    "candidates": [
                        {"value": item["value"], "source": item["source"]}
                        for item in ranked
                    ],
                }
            )
    return fields, sorted(pci_ids)[:128], conflicts


def _manifest_findings(items: dict[str, bytes]) -> list[dict]:
    findings = []
    digests = {name: hashlib.sha256(data).hexdigest() for name, data in items.items()}
    for name, data in sorted(items.items()):
        basename = PurePosixPath(name).name.lower()
        if basename not in {
            "sha256sums",
            "checksums.sha256",
            "manifest.sha256",
            "files.sha256",
        } and not basename.endswith("manifest.txt"):
            continue
        self_ref = False
        self_result = "not_listed"
        other_results: list[str] = []
        malformed = 0
        absolute_paths = False
        for line in data.decode("utf-8", "replace").splitlines():
            if not line.strip():
                continue
            match = _SHA256_LINE.match(line)
            if not match:
                if re.match(r"^[0-9a-fA-F]{64}", line):
                    malformed += 1
                continue
            expected, raw_path = match.groups()
            if raw_path.startswith("/"):
                absolute_paths = True
                matches = [
                    member_name
                    for member_name in items
                    if raw_path.endswith("/" + member_name)
                ]
                candidate = matches[0] if len(matches) == 1 else None
            else:
                try:
                    candidate = _name(raw_path)
                except _Rejected:
                    malformed += 1
                    continue
            actual = digests.get(candidate)
            if candidate == name:
                self_ref = True
                self_result = (
                    "matches_current_bytes"
                    if actual == expected.lower()
                    else "mismatch_generation_defect_possible"
                )
            else:
                other_results.append(
                    "missing"
                    if actual is None
                    else "match"
                    if actual == expected.lower()
                    else "mismatch"
                )
        if not other_results:
            other_result = "not_listed"
        elif all(result == "match" for result in other_results):
            other_result = "all_match"
        elif "mismatch" in other_results:
            other_result = "mismatch_not_explained"
        elif "missing" in other_results:
            other_result = "listed_file_missing"
        else:
            other_result = "unresolved"
        findings.append(
            {
                "path": name,
                "self_reference": self_ref,
                "self_hash_result": self_result,
                "other_files_result": other_result,
                "malformed_lines": malformed,
                "absolute_paths_present": absolute_paths,
            }
        )
    return findings


def _flashrom_findings(items: dict[str, bytes]) -> dict:
    result = {
        "protection_disable_attempt": "not_observed",
        "rom_armor": "not_observed",
        "interpretation": "log text only; command safety and hardware state are not established",
    }
    for name, data in items.items():
        if "flashrom" not in name.lower():
            continue
        text = data.decode("utf-8", "replace")
        if re.search(r"disabl.{0,80}protect", text, re.I | re.S):
            result["protection_disable_attempt"] = (
                "reported_failed"
                if re.search(r"disabl.{0,100}protect.{0,100}fail", text, re.I | re.S)
                else "reported_outcome_unknown"
            )
        if re.search(r"ROM\s+Armor", text, re.I):
            result["rom_armor"] = (
                "possibly_active"
                if re.search(
                    r"ROM\s+Armor.{0,80}possibl|possibl.{0,80}ROM\s+Armor",
                    text,
                    re.I | re.S,
                )
                else "mentioned_unverified"
            )
    return result


def _acpi_findings(items: dict[str, bytes]) -> dict:
    binary = [
        name
        for name, data in items.items()
        if (
            PurePosixPath(name).suffix.lower() == ".aml"
            or PurePosixPath(name).parent.name.lower() == "acpi-tables"
        )
        and data
    ]
    dumps = [
        name
        for name, data in items.items()
        if "acpidump" in PurePosixPath(name).name.lower()
        and PurePosixPath(name).suffix.lower() == ".dat"
        and data
    ]
    dsl = [
        name
        for name, data in items.items()
        if PurePosixPath(name).suffix.lower() == ".dsl" and data
    ]
    attempted = [name for name in items if PurePosixPath(name).suffix.lower() == ".dsl"]
    return {
        "binary_tables_present": len(binary),
        "raw_acpi_dumps_present": len(dumps),
        "dsl_files_present": len(dsl),
        "disassembly": (
            "text_present_completeness_unverified"
            if dsl
            else "attempted_without_text"
            if attempted
            else "not_observed"
        ),
        "external_table_resolution": "not_established",
    }


def _store_report(report: dict, workspace: Path) -> Path:
    if workspace.is_symlink():
        raise _Rejected("workspace symlink is not accepted")
    workspace.mkdir(mode=0o700, parents=True, exist_ok=True)
    if workspace.is_symlink():
        raise _Rejected("workspace symlink is not accepted")
    base = workspace / "surveys"
    if base.is_symlink():
        raise _Rejected("survey storage symlink is not accepted")
    base.mkdir(mode=0o700, exist_ok=True)
    if base.is_symlink():
        raise _Rejected("survey storage symlink is not accepted")
    target_dir = base / report["survey_id"]
    if target_dir.is_symlink():
        raise _Rejected("survey directory symlink is not accepted")
    target_dir.mkdir(mode=0o700, exist_ok=True)
    target = target_dir / "report.json"
    temp = target_dir / f".report-{os.getpid()}-{uuid.uuid4().hex}.tmp"
    content = json.dumps(report, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
        os.replace(temp, target)
    finally:
        if temp.exists():
            temp.unlink()
    return target


def survey_import(source: str | Path, workspace: str | Path) -> dict:
    """Import a directory, tar, or zip without running or extracting it."""
    try:
        items, source_kind = _survey_members(Path(source))
        if not items:
            raise _Rejected("survey contains no regular files")
        files = [
            {
                "path": name,
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "classification": _classify(data),
            }
            for name, data in sorted(items.items())
        ]
        identity = hashlib.sha256(
            json.dumps(
                [(item["path"], item["size"], item["sha256"]) for item in files],
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()
        fields, pci_ids, conflicts = _technical_fields(items)
        report = {
            "status": "ok",
            "kind": "amd_fw_private_survey_report",
            "schema_version": SCHEMA_VERSION,
            "survey_id": f"survey-{identity[:16]}",
            "source_kind": source_kind,
            "collection_exit_status": "unknown",
            "collection_history": "not_established_from_files_alone",
            "files": files,
            "technical_fields": fields,
            "technical_field_conflicts": conflicts,
            "pci_ids": pci_ids,
            "manifests": _manifest_findings(items),
            "flashrom": _flashrom_findings(items),
            "acpi": _acpi_findings(items),
            "privacy": "private_report_do_not_publish",
        }
        report_path = _store_report(report, Path(workspace))
        return {
            "status": "ok",
            "schema_version": SCHEMA_VERSION,
            "survey_id": report["survey_id"],
            "report_path": str(report_path),
            "file_count": len(files),
            "source_kind": source_kind,
        }
    except _Rejected as exc:
        return _failure("rejected", "unsafe_or_unsupported_survey", str(exc))
    except (
        OSError,
        EOFError,
        tarfile.TarError,
        zipfile.BadZipFile,
        RuntimeError,
    ) as exc:
        return _failure("error", "survey_read_failed", type(exc).__name__)


def survey_report(
    survey_id_or_path: str | Path, workspace: str | Path | None = None
) -> dict:
    """Read a normalized private report by ID or explicit JSON path."""
    try:
        candidate = Path(survey_id_or_path)
        if candidate.is_absolute() or (
            candidate.suffix == ".json" and candidate.is_file()
        ):
            path = candidate
        else:
            survey_id = str(survey_id_or_path)
            if not _SURVEY_ID.fullmatch(survey_id):
                raise _Rejected("invalid survey ID")
            if workspace is None:
                raise _Rejected("workspace required for survey ID lookup")
            root = Path(workspace)
            base = root / "surveys"
            survey_dir = base / survey_id
            if any(item.is_symlink() for item in (root, base, survey_dir)):
                raise _Rejected("private survey report path contains a symlink")
            path = survey_dir / "report.json"
        if path.is_symlink() or not path.is_file():
            raise _Rejected("private survey report not found or is a symlink")
        if path.stat().st_size > MAX_REPORT_FILE:
            raise _Rejected("private survey report size limit exceeded")
        with path.open("r", encoding="utf-8") as stream:
            report = json.load(stream)
        if (
            not isinstance(report, dict)
            or report.get("kind") != "amd_fw_private_survey_report"
            or report.get("schema_version") != SCHEMA_VERSION
            or not _SURVEY_ID.fullmatch(str(report.get("survey_id", "")))
        ):
            raise _Rejected("unsupported private survey report schema")
        if not isinstance(report.get("pci_ids"), list):
            raise _Rejected("private survey report PCI IDs must be a list")
        return report
    except _Rejected as exc:
        return _failure("rejected", "invalid_survey_report", str(exc))
    except (OSError, ValueError, TypeError) as exc:
        return _failure("error", "survey_report_read_failed", type(exc).__name__)


def public_export(
    survey_id_or_path: str | Path,
    workspace: str | Path | None = None,
    *,
    reviewed: bool = False,
    destination: str | Path | None = None,
) -> dict:
    """Preview or write an allowlisted case-study JSON record.

    ``reviewed=True`` asserts a human checked the output and publication rights.
    The tool cannot establish complete anonymization.
    """
    report = survey_report(survey_id_or_path, workspace)
    if report.get("status") != "ok":
        return report
    fields = report.get("technical_fields", {})
    if not isinstance(fields, dict):
        return _failure(
            "rejected", "invalid_survey_report", "technical fields must be an object"
        )
    public = {
        "schema_version": SCHEMA_VERSION,
        "kind": "amd_fw_public_survey_case_study",
        "transformation_policy": "technical_allowlist_v1",
        "technical_fields": {
            key: value
            for key, value in fields.items()
            if key in _PUBLIC_FIELDS
            and isinstance(value, str)
            and _technical_value(key, value) == value
        },
        "pci_ids": sorted(
            {
                value
                for value in report.get("pci_ids", [])
                if isinstance(value, str)
                and re.fullmatch(r"[0-9a-f]{4}:[0-9a-f]{4}", value)
            }
        )[:128],
        "limitations": [
            "Collection command exit status and complete history are not established.",
            "This allowlist reduces disclosure risk but is not proof of anonymity.",
            "No hardware validation follows from this survey.",
        ],
    }
    if not reviewed:
        return {
            "status": "review_required",
            "schema_version": SCHEMA_VERSION,
            "preview": public,
            "written": False,
            "review_message": "Inspect every field and confirm publication rights before reviewed export.",
        }
    if destination is not None:
        try:
            path = Path(destination)
            content = (
                json.dumps(public, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
            )
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(content)
        except FileExistsError:
            return _failure(
                "rejected",
                "destination_exists",
                "public export destination already exists",
            )
        except OSError as exc:
            return _failure("error", "public_export_write_failed", type(exc).__name__)
    return {
        "status": "ok",
        "schema_version": SCHEMA_VERSION,
        "data": public,
        "written": destination is not None,
        "destination": str(destination) if destination is not None else None,
    }


def firmware_inspect(path: str | Path) -> dict:
    """Hash a supplied file and identify only a few documented outer headers.

    ZIP member names and sizes come from metadata; contents are not extracted
    or executed. A signature field's presence is never called verification.
    """
    try:
        candidate = Path(path)
        if candidate.is_symlink() or not candidate.is_file():
            raise _Rejected("firmware input must be a regular non-symlink file")
        if candidate.stat().st_size > MAX_FIRMWARE_FILE:
            raise _Rejected("firmware input size limit exceeded")
        fd = os.open(candidate, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as stream:
            metadata = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_size > MAX_FIRMWARE_FILE
            ):
                raise _Rejected("firmware input is not a bounded regular file")
            digest = hashlib.sha256()
            head = b""
            while chunk := stream.read(1024 * 1024):
                if not head:
                    head = chunk[:512]
                digest.update(chunk)
            return _firmware_metadata_report(
                stream, metadata.st_size, digest.hexdigest(), head
            )
    except _Rejected as exc:
        return _failure("rejected", "unsafe_or_unsupported_firmware", str(exc))
    except (OSError, ValueError, EOFError, zipfile.BadZipFile) as exc:
        return _failure("error", "firmware_read_failed", type(exc).__name__)


def _firmware_metadata_report(
    stream: BinaryIO, size: int, digest: str, head: bytes
) -> dict:
    """Interpret bounded outer metadata from the same opened file that was hashed."""
    result = {
        "status": "ok",
        "schema_version": SCHEMA_VERSION,
        "size": size,
        "sha256": digest,
        "format": "opaque",
        "execution": "none",
        "cryptographic_verification": "not_performed",
        "restoration_image_status": "not_established",
        "limitations": [
            "Outer format recognition does not identify all contained firmware components.",
            "An update package is not established as a complete SPI restoration image.",
        ],
    }
    if len(head) >= 28 and head[:16] == FMP_CAPSULE_GUID.bytes_le:
        header_size, flags, image_size = struct.unpack_from("<III", head, 16)
        if 28 <= header_size <= size and image_size == size:
            result["format"] = "uefi_fmp_capsule"
            result["header"] = {
                "capsule_guid": str(FMP_CAPSULE_GUID),
                "header_size": header_size,
                "flags": flags,
                "capsule_image_size": image_size,
            }
        else:
            result["warning"] = (
                "FMP capsule GUID present but header bounds inconsistent"
            )
    elif head.startswith(b"PK\x03\x04") and zipfile.is_zipfile(stream):
        _zip_preflight_stream(
            stream,
            size,
            max_members=MAX_FIRMWARE_MEMBERS,
            max_directory_bytes=MAX_FIRMWARE_ZIP_CENTRAL_DIRECTORY,
        )
        result["format"] = "zip_archive"
        with zipfile.ZipFile(stream) as archive:
            members = archive.infolist()
            if len(members) > MAX_FIRMWARE_MEMBERS:
                raise _Rejected("firmware archive member count limit exceeded")
            if sum(info.file_size for info in members) > MAX_FIRMWARE_EXPANDED:
                raise _Rejected("firmware archive declared expansion limit exceeded")

            def member_kind(info: zipfile.ZipInfo) -> str:
                mode = (info.external_attr >> 16) if info.create_system == 3 else 0
                file_type = stat.S_IFMT(mode)
                if info.is_dir() or file_type == stat.S_IFDIR:
                    return "directory"
                if file_type == stat.S_IFLNK:
                    return "symlink"
                if file_type in (0, stat.S_IFREG):
                    return "file"
                return "special"

            result["members"] = [
                {
                    "name": _name(info.filename),
                    "size": info.file_size,
                    "kind": member_kind(info),
                }
                for info in members
            ]
            result["members_interpretation"] = "metadata_only_not_extracted"
    elif head.startswith(b"\x1f\x8b"):
        result["format"] = "gzip_stream"
    elif head.startswith(b"\xfd7zXZ\x00"):
        result["format"] = "xz_stream"
    elif head.startswith(b"MSCF"):
        result["format"] = "cabinet_archive"
    elif head.startswith(b"MZ"):
        result["format"] = "mz_header_opaque"
    elif len(head) >= 262 and head[257:262] == b"ustar":
        result["format"] = "tar_archive"
    return result
