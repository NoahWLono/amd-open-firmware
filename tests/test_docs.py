"""Check operator instructions against the installed command grammar."""

import re
import shlex
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from amd_fw.cli import _parser  # noqa: E402


class DocumentationTests(unittest.TestCase):
    def test_fish_cli_examples_parse_without_execution(self):
        parser = _parser()
        count = 0
        for name in ("README.md", "RUNBOOK.md", "PROJECT_HANDOFF.md"):
            text = (ROOT / name).read_text(encoding="utf-8")
            in_fish = False
            for line_number, line in enumerate(text.splitlines(), 1):
                if line.strip() == "```fish":
                    in_fish = True
                    continue
                if line.strip() == "```":
                    in_fish = False
                    continue
                if not in_fish or not line.startswith("amd-fw "):
                    continue
                words = shlex.split(line)
                if ">" in words:
                    words = words[: words.index(">")]
                with self.subTest(file=name, line=line_number):
                    parser.parse_args(words[1:])
                count += 1
        self.assertGreaterEqual(count, 20)

    def test_runbook_has_every_required_procedure(self):
        runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
        for letter in "ABCDEFGHIJKLMNOP":
            with self.subTest(procedure=letter):
                self.assertRegex(runbook, rf"(?m)^## {letter}\. ")

    def test_local_document_links_resolve(self):
        docs = [
            ROOT / name for name in ("README.md", "RUNBOOK.md", "PROJECT_HANDOFF.md")
        ]
        docs.extend((ROOT / "docs").rglob("*.md"))
        for document in docs:
            content = document.read_text(encoding="utf-8")
            for link in re.findall(r"\[[^]]+\]\(([^)]+)\)", content):
                if link.startswith(("https://", "http://", "#")):
                    continue
                target = document.parent / link.split("#", 1)[0]
                with self.subTest(document=str(document.relative_to(ROOT)), link=link):
                    self.assertTrue(
                        target.is_file(), f"Broken local document link: {link}"
                    )

    def test_original_markdown_avoids_em_dash(self):
        markdown = list(ROOT.glob("*.md")) + list((ROOT / "docs").rglob("*.md"))
        for path in markdown:
            with self.subTest(document=str(path.relative_to(ROOT))):
                self.assertNotIn("\u2014", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
