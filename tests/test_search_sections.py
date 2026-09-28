from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from tools.search_sections import (
    OUTPUT_SCHEMA_VERSION,
    SEARCH_INDEX_VERSION,
    SECTION_ROOT,
    SearchError,
    build_index,
    ensure_index,
    exact_lookup,
    index_is_current,
    lexical_search,
    load_corpus,
    resolve_regular_file,
    safe_index_path,
    sha256,
)

ROOT = Path(__file__).resolve().parents[1]
TEST_INDEX = Path(f".pi-cache/legal-search/test-{os.getpid()}.sqlite3")


class SearchSectionsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.corpus = load_corpus()
        cls.index_path = safe_index_path(cls.corpus, TEST_INDEX)
        cls.index_path.unlink(missing_ok=True)
        cls.build_metrics = build_index(cls.corpus, TEST_INDEX, reason="test_setup")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.index_path.unlink(missing_ok=True)

    def search(self, query: str, limit: int = 5) -> dict:
        return lexical_search(query, self.corpus, limit, TEST_INDEX)

    def test_exact_lookup_of_section_107(self) -> None:
        result = exact_lookup("107", self.corpus)
        self.assertEqual(result["status"], "FOUND")
        self.assertEqual([item["stable_section_id"] for item in result["candidates"]], ["17-usc-107"])

    def test_exact_lookup_normalizes_multiple_citation_forms(self) -> None:
        for citation in ("107", "§ 107", "17 U.S.C. § 107", "17 USC 107"):
            with self.subTest(citation=citation):
                result = exact_lookup(citation, self.corpus)
                self.assertEqual(result["candidates"][0]["stable_section_id"], "17-usc-107")

    def test_exact_lookup_accepts_alphanumeric_section(self) -> None:
        result = exact_lookup("106A", self.corpus)
        self.assertEqual(result["candidates"][0]["stable_section_id"], "17-usc-106a")
        self.assertEqual(result["candidates"][0]["section_number"], "106A")

    def test_nonexistent_exact_section_is_not_found(self) -> None:
        result = exact_lookup("99999", self.corpus)
        self.assertEqual(result["status"], "NOT_FOUND")
        self.assertEqual(result["result_count"], 0)
        self.assertEqual(result["candidates"], [])

    def test_lexical_heading_query_retrieves_clear_match(self) -> None:
        result = self.search("limitations on exclusive rights fair use")
        self.assertEqual(result["candidates"][0]["stable_section_id"], "17-usc-107")

    def test_lexical_ranking_is_deterministic(self) -> None:
        first = self.search("copyright registration", limit=10)
        second = self.search("copyright registration", limit=10)
        first_rank = [(item["stable_section_id"], item["deterministic_score"]) for item in first["candidates"]]
        second_rank = [(item["stable_section_id"], item["deterministic_score"]) for item in second["candidates"]]
        self.assertEqual(first_rank, second_rank)

    def test_result_limit_is_enforced(self) -> None:
        result = self.search("copyright", limit=3)
        self.assertEqual(result["requested_limit"], 3)
        self.assertEqual(result["result_count"], 3)
        self.assertGreater(result["candidate_count"], result["result_count"])

    def test_json_output_contract_is_stable(self) -> None:
        environment = os.environ.copy()
        for name in tuple(environment):
            if name.endswith("_API_KEY") or name in {"OPENAI_API_KEY", "ANTHROPIC_API_KEY"}:
                environment.pop(name)
        completed = subprocess.run(
            [sys.executable, "tools/search_sections.py", "exact", "107", "--json"],
            cwd=ROOT,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        result = json.loads(completed.stdout)
        self.assertEqual(
            set(result),
            {
                "schema_version", "query", "retrieval_mode", "corpus_id",
                "corpus_source_sha256", "search_index_version", "status",
                "requested_limit", "result_count", "candidate_count",
                "query_latency_ms", "index_build", "candidates",
            },
        )
        self.assertEqual(result["schema_version"], OUTPUT_SCHEMA_VERSION)
        self.assertEqual(result["search_index_version"], SEARCH_INDEX_VERSION)

    def test_every_returned_path_is_in_section_corpus(self) -> None:
        result = self.search("copyright", limit=20)
        allowed = (ROOT / SECTION_ROOT).resolve()
        for candidate in result["candidates"]:
            resolved = (ROOT / candidate["derived_file_path"]).resolve()
            self.assertTrue(resolved.is_relative_to(allowed))

    def test_every_returned_checksum_matches_manifest(self) -> None:
        result = self.search("copyright", limit=20)
        expected = {section.stable_section_id: section.sha256 for section in self.corpus.sections}
        for candidate in result["candidates"]:
            self.assertEqual(candidate["section_file_sha256"], expected[candidate["stable_section_id"]])
            self.assertEqual(sha256(ROOT / candidate["derived_file_path"]), candidate["section_file_sha256"])

    def test_search_does_not_read_evaluator_only(self) -> None:
        sentinel = ROOT / "eval/evaluator-only/legal/.phase3a-sentinel"
        sentinel.write_text("unique-evaluator-only-sentinel-3a", encoding="utf-8")
        try:
            result = self.search("unique evaluator only sentinel 3a", limit=10)
            self.assertNotIn(
                "unique-evaluator-only-sentinel-3a",
                json.dumps(result, ensure_ascii=False),
            )
            self.assertFalse(any("evaluator-only" in item["derived_file_path"] for item in result["candidates"]))
        finally:
            sentinel.unlink(missing_ok=True)

    def test_external_and_traversal_paths_are_rejected(self) -> None:
        for value in ("/etc/passwd", "../eval/evaluator-only/legal"):
            with self.subTest(value=value), self.assertRaises(SearchError):
                resolve_regular_file(ROOT, value, SECTION_ROOT)
        with self.assertRaises(SearchError):
            load_corpus(ROOT.parent)

    def test_corrupt_index_rebuilds_safely(self) -> None:
        corrupt_relative = Path(f".pi-cache/legal-search/corrupt-{os.getpid()}.sqlite3")
        corrupt = safe_index_path(self.corpus, corrupt_relative)
        corrupt.parent.mkdir(parents=True, exist_ok=True)
        corrupt.write_bytes(b"not a sqlite database")
        try:
            metrics = ensure_index(self.corpus, corrupt_relative)
            self.assertIsNotNone(metrics)
            self.assertEqual(metrics["build_reason"], "stale_or_corrupt")
            self.assertTrue(index_is_current(self.corpus, corrupt_relative))
        finally:
            corrupt.unlink(missing_ok=True)

    def test_source_and_corpus_identity_are_validated(self) -> None:
        source_manifest = json.loads((ROOT / "corpus/manifest/title17.json").read_text(encoding="utf-8"))
        sections_manifest = json.loads((ROOT / "corpus/manifest/title17-sections.json").read_text(encoding="utf-8"))
        self.assertEqual(self.corpus.corpus_id, source_manifest["corpus_id"])
        self.assertEqual(self.corpus.corpus_id, sections_manifest["corpus_id"])
        self.assertEqual(self.corpus.source_sha256, source_manifest["xml"]["sha256"])
        self.assertEqual(self.corpus.source_sha256, sections_manifest["source_xml_sha256"])

    def test_build_and_query_metrics_are_separate(self) -> None:
        self.assertIn("build_wall_clock_ms", self.build_metrics)
        self.assertIn("generated_index_byte_size", self.build_metrics)
        self.assertNotIn("query_latency_ms", self.build_metrics)
        result = self.search("fair use")
        self.assertIn("query_latency_ms", result)
        self.assertIsNone(result["index_build"])
        self.assertNotIn("build_wall_clock_ms", result)

    def test_build_and_search_require_no_network(self) -> None:
        offline_relative = Path(f".pi-cache/legal-search/offline-{os.getpid()}.sqlite3")
        offline = safe_index_path(self.corpus, offline_relative)
        offline.unlink(missing_ok=True)
        try:
            with mock.patch.object(socket, "socket", side_effect=AssertionError("network attempted")):
                build_index(self.corpus, offline_relative, reason="offline_test")
                result = lexical_search("fair use", self.corpus, 3, offline_relative)
            self.assertEqual(result["candidates"][0]["stable_section_id"], "17-usc-107")
        finally:
            offline.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
