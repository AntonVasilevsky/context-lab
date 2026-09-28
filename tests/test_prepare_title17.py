from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from tools.prepare_title17 import extract, parse_xml, sha256, validate

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "corpus/source/title17/usc17.xml"
SOURCE_MANIFEST = ROOT / "corpus/manifest/title17.json"
DERIVED_MANIFEST = ROOT / "corpus/manifest/title17-sections.json"


def tree_digest(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(directory.iterdir()):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


class PrepareTitle17Tests(unittest.TestCase):
    def test_pinned_source_parses_and_matches_manifest(self) -> None:
        source_data = json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))
        root = parse_xml(SOURCE).getroot()
        self.assertEqual(root.get("identifier"), "/us/usc/t17")
        self.assertEqual(SOURCE.stat().st_size, source_data["xml"]["byte_size"])
        self.assertEqual(sha256(SOURCE), source_data["xml"]["sha256"])

    def test_official_archive_matches_manifest_and_extracted_xml(self) -> None:
        source_data = json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))
        archive = ROOT / source_data["artifact"]["repository_path"]
        self.assertEqual(archive.stat().st_size, source_data["artifact"]["byte_size"])
        self.assertEqual(sha256(archive), source_data["artifact"]["sha256"])
        with zipfile.ZipFile(archive) as bundle:
            self.assertEqual(bundle.namelist(), [source_data["xml"]["archive_member"]])
            self.assertEqual(bundle.read(source_data["xml"]["archive_member"]), SOURCE.read_bytes())

    def test_checked_in_derived_corpus_validates(self) -> None:
        validate(DERIVED_MANIFEST)

    def test_repeated_extraction_has_identical_contents_and_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            first_output = base / "first"
            second_output = base / "second"
            first_manifest = base / "first.json"
            second_manifest = base / "second.json"
            timestamp = "2026-09-28T12:00:00Z"
            first = extract(SOURCE, SOURCE_MANIFEST, first_output, first_manifest, timestamp)
            second = extract(SOURCE, SOURCE_MANIFEST, second_output, second_manifest, timestamp)
            self.assertGreater(first["total_section_count"], 0)
            self.assertEqual(first, second)
            self.assertEqual(tree_digest(first_output), tree_digest(second_output))
            self.assertEqual(first_manifest.read_bytes(), second_manifest.read_bytes())


if __name__ == "__main__":
    unittest.main()
