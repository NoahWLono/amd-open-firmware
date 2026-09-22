"""Behavioral tests for bounded, offline private-input analysis."""

from __future__ import annotations

import hashlib
import gzip
import io
import json
import os
from pathlib import Path
import struct
import stat
import tarfile
import tempfile
import unittest
import uuid
import zipfile
from unittest import mock

from amd_fw.offline import firmware_inspect, public_export, survey_import, survey_report


class OfflineSurveyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / "private workspace"

    def test_import_classifies_gaps_without_claiming_command_success(self) -> None:
        source = self.root / "synthetic survey"
        (source / "dmi").mkdir(parents=True)
        (source / "dmi" / "board_name").write_text("SYNTH-BOARD\n")
        (source / "lshw.txt").write_text("lshw: command not found\n")
        (source / "empty.txt").write_bytes(b"")
        (source / "flashrom.log").write_text(
            "Attempting to disable write protection failed. "
            "ROM Armor is possibly active.\n"
        )
        (source / "DSDT.dsl").write_text("DefinitionBlock (...) {}\n")

        result = survey_import(source, self.workspace)
        self.assertEqual(result["status"], "ok")
        report = survey_report(result["survey_id"], self.workspace)
        self.assertEqual(report["status"], "ok")
        files = {item["path"]: item for item in report["files"]}
        self.assertEqual(files["lshw.txt"]["classification"], "missing_utility")
        self.assertEqual(files["empty.txt"]["classification"], "empty")
        self.assertEqual(
            files["dmi/board_name"]["classification"], "content_present_exit_unknown"
        )
        self.assertEqual(report["technical_fields"]["board_name"], "SYNTH-BOARD")
        self.assertEqual(report["collection_exit_status"], "unknown")
        self.assertEqual(
            report["flashrom"]["protection_disable_attempt"], "reported_failed"
        )
        self.assertEqual(report["flashrom"]["rom_armor"], "possibly_active")
        self.assertEqual(
            report["acpi"]["disassembly"], "text_present_completeness_unverified"
        )
        self.assertNotIn("success", json.dumps(report).lower())

    def test_rejects_tar_traversal_and_symlink_without_writing_raw_files(self) -> None:
        for kind in ("traversal", "symlink"):
            with self.subTest(kind=kind):
                archive = self.root / f"{kind}.tar"
                with tarfile.open(archive, "w") as tar:
                    if kind == "traversal":
                        payload = b"escape"
                        info = tarfile.TarInfo("../outside.txt")
                        info.size = len(payload)
                        tar.addfile(info, io.BytesIO(payload))
                    else:
                        info = tarfile.TarInfo("alias")
                        info.type = tarfile.SYMTYPE
                        info.linkname = "/etc/passwd"
                        tar.addfile(info)
                result = survey_import(archive, self.workspace)
                self.assertEqual(result["status"], "rejected")
                self.assertFalse((self.root / "outside.txt").exists())
                self.assertFalse((self.workspace / "surveys").exists())

    def test_imports_small_gzip_tar_with_same_normalized_report(self) -> None:
        archive = self.root / "synthetic survey.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            payload = b"board_name: SYNTH-BOARD\n"
            info = tarfile.TarInfo("00-summary.txt")
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
        imported = survey_import(archive, self.workspace)
        self.assertEqual(imported["status"], "ok")
        report = survey_report(imported["survey_id"], self.workspace)
        self.assertEqual(report["technical_fields"]["board_name"], "SYNTH-BOARD")

    def test_rejects_zip_traversal_and_symlink(self) -> None:
        archive = self.root / "bad.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("../outside.txt", "escape")
        self.assertEqual(survey_import(archive, self.workspace)["status"], "rejected")

        archive = self.root / "link.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            info = zipfile.ZipInfo("link")
            info.create_system = 3
            info.external_attr = 0o120777 << 16
            zf.writestr(info, "/etc/passwd")
        self.assertEqual(survey_import(archive, self.workspace)["status"], "rejected")

    def test_rejects_directory_symlink_and_executable_member(self) -> None:
        source = self.root / "source"
        source.mkdir()
        (source / "escape").symlink_to("/etc/passwd")
        self.assertEqual(survey_import(source, self.workspace)["status"], "rejected")
        (source / "escape").unlink()
        script = source / "run.sh"
        script.write_text("#!/bin/sh\necho unexpected\n")
        self.assertEqual(survey_import(source, self.workspace)["status"], "rejected")

    def test_private_report_refuses_symlinked_surveys_directory(self) -> None:
        source = self.root / "synthetic source"
        source.mkdir()
        (source / "board_name").write_text("SYNTH-BOARD\n", encoding="utf-8")
        outside = self.root / "outside"
        outside.mkdir()
        self.workspace.mkdir()
        (self.workspace / "surveys").symlink_to(outside, target_is_directory=True)
        imported = survey_import(source, self.workspace)
        self.assertEqual(imported["status"], "rejected")
        self.assertEqual(list(outside.iterdir()), [])
        self.assertEqual(
            survey_report("survey-" + "0" * 16, self.workspace)["status"], "rejected"
        )

    def test_rejects_member_over_size_limit(self) -> None:
        source = self.root / "source"
        source.mkdir()
        with (source / "oversize.bin").open("wb") as stream:
            stream.truncate(8 * 1024 * 1024 + 1)
        self.assertEqual(survey_import(source, self.workspace)["status"], "rejected")

    def test_self_referential_manifest_is_reported_as_generation_defect_candidate(
        self,
    ) -> None:
        source = self.root / "source"
        source.mkdir()
        (source / "cpuinfo").write_text("vendor_id : AuthenticAMD\n")
        (source / "SHA256SUMS").write_text("0" * 64 + "  SHA256SUMS\n")
        result = survey_import(source, self.workspace)
        report = survey_report(result["survey_id"], self.workspace)
        self.assertEqual(report["manifests"][0]["self_reference"], True)
        self.assertEqual(
            report["manifests"][0]["self_hash_result"],
            "mismatch_generation_defect_possible",
        )
        self.assertEqual(report["manifests"][0]["other_files_result"], "not_listed")
        self.assertNotIn("report.json", [item["path"] for item in report["files"]])

    def test_prefixed_survey_summary_and_absolute_manifest_are_normalized(self) -> None:
        source = self.root / "survey"
        source.mkdir()
        (source / "00-summary.txt").write_text(
            "Vendor ID: AuthenticAMD\nModel name: Synthetic AMD CPU\n"
            "CPU family: 25\nModel: 80\nboard_name: SYNTH-BOARD\n"
            "board_version: SYNTH-REV-7\nbios_version: SYNTH-FW-2\n"
            "bios_date: 02/03/2025\n"
        )
        (source / "07-flashrom-probe.txt").write_text(
            "Enabling flash write... Disabling read write protection failed.\n"
            "ROM Armor is possibly active.\n"
        )
        summary_digest = hashlib.sha256(
            (source / "00-summary.txt").read_bytes()
        ).hexdigest()
        (source / "11-manifest.txt").write_text(
            "=== SHA256 ===\n"
            f"{summary_digest}  /home/example/survey/00-summary.txt\n"
            + "0" * 64
            + "  /home/example/survey/11-manifest.txt\n"
        )
        imported = survey_import(source, self.workspace)
        report = survey_report(imported["survey_id"], self.workspace)
        self.assertEqual(
            report["technical_fields"]["cpu_model_name"], "Synthetic AMD CPU"
        )
        self.assertEqual(report["technical_fields"]["board_name"], "SYNTH-BOARD")
        self.assertEqual(report["technical_fields"]["bios_date"], "2025-02-03")
        self.assertEqual(
            report["flashrom"]["protection_disable_attempt"], "reported_failed"
        )
        self.assertEqual(
            report["manifests"][0]["self_hash_result"],
            "mismatch_generation_defect_possible",
        )
        self.assertEqual(report["manifests"][0]["other_files_result"], "all_match")
        self.assertTrue(report["manifests"][0]["absolute_paths_present"])

    def test_raw_diagnostics_override_conflicting_summary_values_and_record_conflicts(
        self,
    ) -> None:
        source = self.root / "survey"
        source.mkdir()
        (source / "00-summary.txt").write_text(
            "board_name: SUMMARY-BOARD\n"
            "bios_version: SUMMARY-BIOS\n"
            "Model name: SUMMARY-CPU\n"
        )
        (source / "01-dmidecode.txt").write_text(
            "BIOS Information\n\tVersion: RAW-BIOS\n"
            "Base Board Information\n\tProduct Name: RAW-BOARD\n"
        )
        (source / "02-cpuinfo.txt").write_text("model name : RAW-CPU\n")

        imported = survey_import(source, self.workspace)
        report = survey_report(imported["survey_id"], self.workspace)
        self.assertEqual(report["technical_fields"]["board_name"], "RAW-BOARD")
        self.assertEqual(report["technical_fields"]["bios_version"], "RAW-BIOS")
        self.assertEqual(report["technical_fields"]["cpu_model_name"], "RAW-CPU")
        conflicts = {
            item["field"]: item for item in report["technical_field_conflicts"]
        }
        self.assertEqual(
            {"board_name", "bios_version", "cpu_model_name"}, set(conflicts)
        )
        self.assertEqual(conflicts["board_name"]["selected_value"], "RAW-BOARD")
        self.assertEqual(
            {candidate["value"] for candidate in conflicts["board_name"]["candidates"]},
            {"SUMMARY-BOARD", "RAW-BOARD"},
        )

    def test_dmidecode_unrecognized_section_does_not_bleed_into_board_fields(
        self,
    ) -> None:
        source = self.root / "source"
        source.mkdir()
        (source / "01-dmidecode.txt").write_text(
            "Base Board Information\n\tProduct Name: RAW-BOARD\n"
            "Chassis Information\n\tVersion: CHASSIS-ONLY\n"
        )
        imported = survey_import(source, self.workspace)
        report = survey_report(imported["survey_id"], self.workspace)
        self.assertEqual(report["technical_fields"]["board_name"], "RAW-BOARD")
        self.assertNotIn("board_version", report["technical_fields"])

    def test_directory_entries_count_toward_limit_for_tar_zip_and_directory(
        self,
    ) -> None:
        tar_path = self.root / "many-dirs.tar"
        with tarfile.open(tar_path, "w") as tar:
            payload = b"synthetic"
            info = tarfile.TarInfo("data.txt")
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
            for index in range(512):
                directory = tarfile.TarInfo(f"d{index:03d}/")
                directory.type = tarfile.DIRTYPE
                tar.addfile(directory)

        zip_path = self.root / "many-dirs.zip"
        with zipfile.ZipFile(zip_path, "w") as archive:
            archive.writestr("data.txt", "synthetic")
            for index in range(512):
                archive.writestr(f"d{index:03d}/", "")

        source_dir = self.root / "many-dirs"
        source_dir.mkdir()
        (source_dir / "data.txt").write_text("synthetic")
        for index in range(512):
            (source_dir / f"d{index:03d}").mkdir()

        for source in (tar_path, zip_path, source_dir):
            with self.subTest(source=source.name):
                result = survey_import(source, self.workspace)
                self.assertEqual(result["status"], "rejected")
                self.assertIn("count limit", result["error"]["detail"])

    def test_zip_rejects_large_central_directory_metadata_before_parsing_members(
        self,
    ) -> None:
        archive = self.root / "large-central-directory.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("data.txt", "synthetic")
            for index in range(40):
                entry = zipfile.ZipInfo(f"d{index:03d}/")
                entry.comment = b"A" * 60000
                zf.writestr(entry, b"")
        result = survey_import(archive, self.workspace)
        self.assertEqual(result["status"], "rejected")
        self.assertIn("central directory metadata limit", result["error"]["detail"])

    def test_compressed_tar_stream_limit_applies_before_pax_parsing(self) -> None:
        archive = self.root / "oversized-metadata.tar.gz"
        with gzip.open(archive, "wb") as stream:
            chunk = b"\x00" * (1024 * 1024)
            for _ in range(41):
                stream.write(chunk)
        result = survey_import(archive, self.workspace)
        self.assertEqual(result["status"], "rejected")
        self.assertIn("tar stream size limit", result["error"]["detail"])

    def test_acpi_dump_is_distinct_from_individual_binary_tables(self) -> None:
        source = self.root / "source"
        (source / "acpi-tables").mkdir(parents=True)
        (source / "acpi-disassembly").mkdir()
        (source / "acpi-tables" / "DSDT").write_bytes(b"\x00binary table")
        (source / "03-acpidump.dat").write_bytes(b"\x00combined dump")
        (source / "acpi-disassembly" / "DSDT.dsl").write_text(
            "DefinitionBlock (...) {}"
        )
        imported = survey_import(source, self.workspace)
        report = survey_report(imported["survey_id"], self.workspace)
        self.assertEqual(report["acpi"]["binary_tables_present"], 1)
        self.assertEqual(report["acpi"]["raw_acpi_dumps_present"], 1)
        self.assertEqual(report["acpi"]["dsl_files_present"], 1)

    def test_public_export_requires_review_and_excludes_private_values(self) -> None:
        source = self.root / "source"
        (source / "dmi").mkdir(parents=True)
        (source / "dmi" / "board_name").write_text("SYNTH-BOARD\n")
        (source / "dmi" / "board_serial").write_text("PRIVATE-SERIAL-123\n")
        (source / "lspci.txt").write_text(
            "00:00.0 Host bridge [0600]: Example [1022:1480]\n"
        )
        imported = survey_import(source, self.workspace)
        destination = self.root / "public.json"
        preview = public_export(
            imported["survey_id"], self.workspace, destination=destination
        )
        self.assertEqual(preview["status"], "review_required")
        self.assertFalse(destination.exists())
        exported = public_export(
            imported["survey_id"],
            self.workspace,
            reviewed=True,
            destination=destination,
        )
        self.assertEqual(exported["status"], "ok")
        public_text = destination.read_text()
        self.assertIn("SYNTH-BOARD", public_text)
        self.assertIn("1022:1480", public_text)
        self.assertNotIn("PRIVATE-SERIAL-123", public_text)
        self.assertNotIn(str(source), public_text)
        self.assertNotIn("board_serial", public_text)
        self.assertNotIn(imported["survey_id"], public_text)

    def test_public_export_rejects_malformed_pci_ids_in_private_report(self) -> None:
        source = self.root / "source"
        source.mkdir()
        (source / "board_name").write_text("SYNTH-BOARD")
        imported = survey_import(source, self.workspace)
        report_path = Path(imported["report_path"])
        stored = json.loads(report_path.read_text())
        stored["pci_ids"] = None
        report_path.write_text(json.dumps(stored))

        result = public_export(imported["survey_id"], self.workspace, reviewed=True)
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["error"]["code"], "invalid_survey_report")

    def test_report_id_cannot_escape_workspace(self) -> None:
        result = survey_report("../../outside", self.workspace)
        self.assertEqual(result["status"], "rejected")


class FirmwareInspectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_unknown_bytes_are_opaque_hashed_and_not_verified(self) -> None:
        payload = b"unknown vendor blob\x00"
        path = self.root / "firmware.bin"
        path.write_bytes(payload)
        report = firmware_inspect(path)
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["format"], "opaque")
        self.assertEqual(report["sha256"], hashlib.sha256(payload).hexdigest())
        self.assertEqual(report["size"], len(payload))
        self.assertEqual(report["cryptographic_verification"], "not_performed")
        self.assertEqual(report["restoration_image_status"], "not_established")

    def test_recognizes_only_bounds_consistent_standard_capsule_header(self) -> None:
        guid = uuid.UUID("6dcbd5ed-e82d-4c44-bda1-7194199ad92a")
        payload = guid.bytes_le + struct.pack("<III", 28, 0, 32) + b"data"
        path = self.root / "update.cap"
        path.write_bytes(payload)
        report = firmware_inspect(path)
        self.assertEqual(report["format"], "uefi_fmp_capsule")
        self.assertEqual(report["header"]["capsule_image_size"], 32)
        path.write_bytes(payload[:-1])
        self.assertEqual(firmware_inspect(path)["format"], "opaque")

    def test_zip_is_inventoried_without_executing_installer(self) -> None:
        path = self.root / "vendor.zip"
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("setup.exe", b"MZ" + b"\x00" * 10)
            zf.writestr("payload.bin", b"blob")
        report = firmware_inspect(path)
        self.assertEqual(report["format"], "zip_archive")
        self.assertEqual(
            {entry["name"] for entry in report["members"]}, {"setup.exe", "payload.bin"}
        )
        self.assertEqual(report["execution"], "none")

    def test_zip_inventory_identifies_symlink_without_extracting_it(self) -> None:
        path = self.root / "vendor-links.zip"
        with zipfile.ZipFile(path, "w") as archive:
            link = zipfile.ZipInfo("firmware-link")
            link.create_system = 3
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(link, "firmware.bin")
        report = firmware_inspect(path)
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["members"][0]["kind"], "symlink")

    def test_zip_inventory_uses_the_same_open_file_as_its_hash(self) -> None:
        path = self.root / "vendor.zip"
        replacement = self.root / "replacement.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("first.bin", b"first")
        with zipfile.ZipFile(replacement, "w") as archive:
            archive.writestr("second.bin", b"second")
        expected_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        original_is_zipfile = zipfile.is_zipfile

        def replace_before_inventory(file_or_path):
            os.replace(replacement, path)
            return original_is_zipfile(file_or_path)

        with mock.patch(
            "amd_fw.offline.zipfile.is_zipfile", side_effect=replace_before_inventory
        ):
            report = firmware_inspect(path)
        self.assertEqual(report["sha256"], expected_hash)
        self.assertEqual([item["name"] for item in report["members"]], ["first.bin"])

    def test_firmware_zip_member_limit_is_checked_before_parsing_entries(self) -> None:
        path = self.root / "many-firmware-members.zip"
        with zipfile.ZipFile(path, "w") as archive:
            for index in range(1025):
                archive.writestr(f"member-{index:04d}/", b"")
        with mock.patch(
            "amd_fw.offline.zipfile.ZipFile",
            side_effect=AssertionError("member parser ran before preflight"),
        ):
            report = firmware_inspect(path)
        self.assertEqual(report["status"], "rejected")
        self.assertIn("member count", report["error"]["detail"])

    def test_mz_prefix_is_not_treated_as_parsed_firmware(self) -> None:
        path = self.root / "vendor-installer.bin"
        path.write_bytes(b"MZ" + b"not a validated PE image")
        report = firmware_inspect(path)
        self.assertEqual(report["format"], "mz_header_opaque")
        self.assertEqual(report["cryptographic_verification"], "not_performed")


if __name__ == "__main__":
    unittest.main()
