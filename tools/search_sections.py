#!/usr/bin/env python3
"""Deterministic exact and lexical candidate retrieval for the pinned Title 17 corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SEARCH_INDEX_VERSION = "title17-fts5-v1"
OUTPUT_SCHEMA_VERSION = 1
ROOT = Path(__file__).resolve().parents[1]
SOURCE_MANIFEST = Path("corpus/manifest/title17.json")
SECTIONS_MANIFEST = Path("corpus/manifest/title17-sections.json")
SECTION_ROOT = Path("corpus/sections/title17")
DEFAULT_INDEX = Path(".pi-cache/legal-search/title17-fts5-v1.sqlite3")
EXACT_CITATION = re.compile(
    r"^\s*(?:(?:17\s+U\.?\s*S\.?\s*C\.?)\s*)?(?:§\s*)?([0-9]+[A-Za-z]?)\s*$",
    re.IGNORECASE,
)
TOKEN = re.compile(r"[^\W_]+", re.UNICODE)


class SearchError(ValueError):
    """Raised when corpus or index validation fails closed."""


@dataclass(frozen=True)
class Section:
    stable_section_id: str
    citation: str
    section_number: str
    heading: str
    derived_file_path: str
    sha256: str
    xml_byte_size: int


@dataclass(frozen=True)
class Corpus:
    root: Path
    corpus_id: str
    source_sha256: str
    sections_manifest_sha256: str
    sections: tuple[Section, ...]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def resolve_regular_file(root: Path, relative: str, allowed_root: Path) -> Path:
    supplied = Path(relative)
    if supplied.is_absolute() or ".." in supplied.parts:
        raise SearchError(f"unsafe corpus path: {relative}")
    lexical = root / supplied
    current = root
    for part in supplied.parts:
        current = current / part
        if current.is_symlink():
            raise SearchError(f"corpus symlink is forbidden: {relative}")
    try:
        resolved = lexical.resolve(strict=True)
    except OSError as error:
        raise SearchError(f"missing corpus file: {relative}") from error
    allowed = (root / allowed_root).resolve(strict=True)
    if not is_within(resolved, allowed) or not resolved.is_file():
        raise SearchError(f"corpus path is outside the allowed tree: {relative}")
    return resolved


def load_corpus(root: Path = ROOT) -> Corpus:
    root = root.resolve(strict=True)
    if root != ROOT.resolve(strict=True):
        raise SearchError("corpus root is fixed to the repository containing this tool")
    source_manifest_path = resolve_regular_file(root, SOURCE_MANIFEST.as_posix(), SOURCE_MANIFEST.parent)
    sections_manifest_path = resolve_regular_file(root, SECTIONS_MANIFEST.as_posix(), SECTIONS_MANIFEST.parent)
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    sections_manifest = json.loads(sections_manifest_path.read_text(encoding="utf-8"))

    if source_manifest.get("corpus_id") != sections_manifest.get("corpus_id"):
        raise SearchError("source and section corpus identities differ")
    expected_source_sha = source_manifest.get("xml", {}).get("sha256")
    if not expected_source_sha or sections_manifest.get("source_xml_sha256") != expected_source_sha:
        raise SearchError("source and section manifests disagree on source XML identity")
    source_path = resolve_regular_file(
        root,
        source_manifest["xml"]["repository_path"],
        Path("corpus/source/title17"),
    )
    if source_path.stat().st_size != source_manifest["xml"]["byte_size"] or sha256(source_path) != expected_source_sha:
        raise SearchError("pinned source XML identity validation failed")

    raw_entries = sections_manifest.get("sections")
    if not isinstance(raw_entries, list) or sections_manifest.get("total_section_count") != len(raw_entries):
        raise SearchError("section manifest count is invalid")

    sections: list[Section] = []
    seen_ids: set[str] = set()
    seen_numbers: set[str] = set()
    for entry in raw_entries:
        path = resolve_regular_file(root, entry["derived_file_path"], SECTION_ROOT)
        if entry.get("source_xml_sha256") != expected_source_sha:
            raise SearchError(f"section has a different source identity: {entry.get('stable_section_id')}")
        actual_sha = sha256(path)
        if actual_sha != entry["sha256"]:
            raise SearchError(f"section checksum mismatch: {entry['derived_file_path']}")
        stable_id = entry["stable_section_id"]
        section_number = entry["section_number"]
        if stable_id in seen_ids or section_number.casefold() in seen_numbers:
            raise SearchError("duplicate section identity in manifest")
        seen_ids.add(stable_id)
        seen_numbers.add(section_number.casefold())
        sections.append(
            Section(
                stable_section_id=stable_id,
                citation=entry["citation"],
                section_number=section_number,
                heading=entry["heading"],
                derived_file_path=entry["derived_file_path"],
                sha256=entry["sha256"],
                xml_byte_size=path.stat().st_size,
            )
        )
    if not sections:
        raise SearchError("section corpus is empty")

    return Corpus(
        root=root,
        corpus_id=source_manifest["corpus_id"],
        source_sha256=expected_source_sha,
        sections_manifest_sha256=sha256(sections_manifest_path),
        sections=tuple(sections),
    )


def normalize_search_text(text: str) -> str:
    """NFC-normalize, Unicode case-fold, and collapse whitespace."""
    return " ".join(unicodedata.normalize("NFC", text).casefold().split())


def lexical_terms(text: str) -> list[str]:
    return TOKEN.findall(normalize_search_text(text))


def extract_searchable_text(path: Path) -> str:
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as error:
        raise SearchError(f"invalid derived section XML: {path}") from error
    return normalize_search_text(" ".join(root.itertext()))


def normalize_exact_section(query: str) -> str | None:
    match = EXACT_CITATION.fullmatch(unicodedata.normalize("NFC", query).replace("\u00a0", " "))
    return match.group(1).casefold() if match else None


def safe_index_path(corpus: Corpus, requested: Path = DEFAULT_INDEX) -> Path:
    if requested.is_absolute() or ".." in requested.parts:
        raise SearchError("index path must be repository-relative local state")
    allowed = corpus.root / ".pi-cache" / "legal-search"
    current = corpus.root
    for part in requested.parts:
        current = current / part
        if current.is_symlink():
            raise SearchError(f"index path symlink is forbidden: {requested}")
    lexical = corpus.root / requested
    try:
        lexical.relative_to(allowed)
    except ValueError as error:
        raise SearchError("index path must be under .pi-cache/legal-search") from error
    return lexical


def expected_metadata(corpus: Corpus) -> dict[str, str]:
    return {
        "search_index_version": SEARCH_INDEX_VERSION,
        "corpus_id": corpus.corpus_id,
        "corpus_source_sha256": corpus.source_sha256,
        "sections_manifest_sha256": corpus.sections_manifest_sha256,
        "section_count": str(len(corpus.sections)),
        "normalization": "NFC; Unicode casefold; whitespace collapse; document-order XML itertext",
        "ranking": (
            "integer score: exact section 100000; exact heading 20000; heading phrase 10000; "
            "text phrase 2000; per-term section 1000, citation 500, heading frequency 200, "
            "text frequency 10, coverage 100; ties use manifest ordinal"
        ),
    }


def build_index(corpus: Corpus, requested_index: Path = DEFAULT_INDEX, reason: str = "explicit") -> dict[str, Any]:
    started = time.perf_counter_ns()
    index_path = safe_index_path(corpus, requested_index)
    parent = index_path.parent
    if parent.exists() and (parent.is_symlink() or not parent.is_dir()):
        raise SearchError("legal-search cache path is not a real directory")
    parent.mkdir(parents=True, exist_ok=True)
    temporary = index_path.with_suffix(index_path.suffix + ".tmp")
    if temporary.is_symlink() or index_path.is_symlink():
        raise SearchError("index output may not be a symlink")
    if temporary.exists():
        temporary.unlink()

    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(temporary)
        connection.executescript(
            """
            PRAGMA journal_mode=OFF;
            PRAGMA synchronous=OFF;
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID;
            CREATE TABLE sections (
                ordinal INTEGER PRIMARY KEY,
                stable_section_id TEXT NOT NULL UNIQUE,
                citation TEXT NOT NULL,
                section_number TEXT NOT NULL UNIQUE,
                heading TEXT NOT NULL,
                normalized_heading TEXT NOT NULL,
                searchable_text TEXT NOT NULL,
                derived_file_path TEXT NOT NULL,
                section_file_sha256 TEXT NOT NULL,
                xml_byte_size INTEGER NOT NULL,
                searchable_text_character_count INTEGER NOT NULL
            );
            CREATE VIRTUAL TABLE sections_fts USING fts5(
                stable_section_id UNINDEXED,
                section_number,
                citation,
                heading,
                searchable_text,
                tokenize='unicode61 remove_diacritics 2'
            );
            """
        )
        connection.executemany(
            "INSERT INTO metadata(key, value) VALUES (?, ?)", sorted(expected_metadata(corpus).items())
        )
        for ordinal, section in enumerate(corpus.sections, start=1):
            path = corpus.root / section.derived_file_path
            searchable = extract_searchable_text(path)
            normalized_heading = normalize_search_text(section.heading)
            connection.execute(
                "INSERT INTO sections VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    ordinal,
                    section.stable_section_id,
                    section.citation,
                    section.section_number,
                    section.heading,
                    normalized_heading,
                    searchable,
                    section.derived_file_path,
                    section.sha256,
                    section.xml_byte_size,
                    len(searchable),
                ),
            )
            connection.execute(
                "INSERT INTO sections_fts(rowid, stable_section_id, section_number, citation, heading, searchable_text) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    ordinal,
                    section.stable_section_id,
                    normalize_search_text(section.section_number),
                    normalize_search_text(section.citation),
                    normalized_heading,
                    searchable,
                ),
            )
        connection.commit()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise SearchError(f"new index failed integrity check: {integrity}")
        connection.close()
        connection = None
        os.replace(temporary, index_path)
    except (OSError, sqlite3.DatabaseError, SearchError):
        if connection is not None:
            connection.close()
        if temporary.exists() and not temporary.is_symlink():
            temporary.unlink()
        raise

    elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
    return {
        "corpus_id": corpus.corpus_id,
        "corpus_source_sha256": corpus.source_sha256,
        "section_count": len(corpus.sections),
        "build_wall_clock_ms": round(elapsed_ms, 3),
        "generated_index_byte_size": index_path.stat().st_size,
        "search_index_version": SEARCH_INDEX_VERSION,
        "index_path": index_path.relative_to(corpus.root).as_posix(),
        "build_reason": reason,
    }


def index_is_current(corpus: Corpus, requested_index: Path = DEFAULT_INDEX) -> bool:
    index_path = safe_index_path(corpus, requested_index)
    if not index_path.is_file() or index_path.is_symlink():
        return False
    try:
        connection = sqlite3.connect(f"file:{index_path}?mode=ro", uri=True)
        try:
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                return False
            actual = dict(connection.execute("SELECT key, value FROM metadata"))
            if actual != expected_metadata(corpus):
                return False
            count = connection.execute("SELECT COUNT(*) FROM sections").fetchone()[0]
            fts_count = connection.execute("SELECT COUNT(*) FROM sections_fts").fetchone()[0]
            return count == fts_count == len(corpus.sections)
        finally:
            connection.close()
    except sqlite3.DatabaseError:
        return False


def ensure_index(corpus: Corpus, requested_index: Path = DEFAULT_INDEX) -> dict[str, Any] | None:
    index_path = safe_index_path(corpus, requested_index)
    if index_is_current(corpus, requested_index):
        return None
    reason = "missing" if not index_path.exists() else "stale_or_corrupt"
    if index_path.exists():
        if index_path.is_symlink() or not index_path.is_file():
            raise SearchError("stale index is not a replaceable regular file")
        index_path.unlink()
    return build_index(corpus, requested_index, reason=reason)


def base_output(query: str, mode: str, corpus: Corpus, requested_limit: int) -> dict[str, Any]:
    return {
        "schema_version": OUTPUT_SCHEMA_VERSION,
        "query": query,
        "retrieval_mode": mode,
        "corpus_id": corpus.corpus_id,
        "corpus_source_sha256": corpus.source_sha256,
        "search_index_version": SEARCH_INDEX_VERSION,
        "status": "NOT_FOUND",
        "requested_limit": requested_limit,
        "result_count": 0,
        "candidate_count": 0,
        "query_latency_ms": 0.0,
        "index_build": None,
        "candidates": [],
    }


def candidate_base(section: Section, searchable_text_character_count: int) -> dict[str, Any]:
    return {
        "stable_section_id": section.stable_section_id,
        "citation": section.citation,
        "section_number": section.section_number,
        "heading": section.heading,
        "derived_file_path": section.derived_file_path,
        "section_file_sha256": section.sha256,
        "xml_byte_size": section.xml_byte_size,
        "searchable_text_character_count": searchable_text_character_count,
    }


def exact_lookup(query: str, corpus: Corpus) -> dict[str, Any]:
    started = time.perf_counter_ns()
    output = base_output(query, "EXACT", corpus, 1)
    requested = normalize_exact_section(query)
    if requested is not None:
        for section in corpus.sections:
            if section.section_number.casefold() == requested:
                searchable = extract_searchable_text(corpus.root / section.derived_file_path)
                candidate = candidate_base(section, len(searchable))
                candidate.update(
                    {
                        "rank": 1,
                        "deterministic_score": 100000,
                        "ranking_metadata": {"match": "normalized_section_number"},
                    }
                )
                output.update(
                    {
                        "status": "FOUND",
                        "result_count": 1,
                        "candidate_count": 1,
                        "candidates": [candidate],
                    }
                )
                break
    output["query_latency_ms"] = round((time.perf_counter_ns() - started) / 1_000_000, 3)
    return output


def score_candidate(query_normalized: str, terms: list[str], row: sqlite3.Row) -> tuple[int, dict[str, Any]]:
    unique_terms = list(dict.fromkeys(terms))
    heading_tokens = lexical_terms(row["normalized_heading"])
    text_tokens = lexical_terms(row["searchable_text"])
    citation_tokens = lexical_terms(row["citation"])
    section_tokens = lexical_terms(row["section_number"])

    exact_section = query_normalized == normalize_search_text(row["section_number"])
    exact_heading = query_normalized == row["normalized_heading"]
    heading_phrase = bool(query_normalized and query_normalized in row["normalized_heading"])
    text_phrase = bool(query_normalized and query_normalized in row["searchable_text"])
    term_score = 0
    covered = 0
    for term in unique_terms:
        counts = (
            section_tokens.count(term),
            citation_tokens.count(term),
            heading_tokens.count(term),
            text_tokens.count(term),
        )
        if any(counts):
            covered += 1
        term_score += counts[0] * 1000 + counts[1] * 500 + counts[2] * 200 + counts[3] * 10
    score = (
        int(exact_section) * 100000
        + int(exact_heading) * 20000
        + int(heading_phrase) * 10000
        + int(text_phrase) * 2000
        + term_score
        + covered * 100
    )
    return score, {
        "exact_section": exact_section,
        "exact_heading": exact_heading,
        "heading_phrase": heading_phrase,
        "text_phrase": text_phrase,
        "matched_unique_terms": covered,
        "query_unique_terms": len(unique_terms),
        "tie_breaker": "section manifest ordinal",
    }


def lexical_search(
    query: str,
    corpus: Corpus,
    limit: int = 5,
    requested_index: Path = DEFAULT_INDEX,
) -> dict[str, Any]:
    if limit < 1 or limit > 100:
        raise SearchError("limit must be between 1 and 100")
    output = base_output(query, "LEXICAL", corpus, limit)
    output["index_build"] = ensure_index(corpus, requested_index)
    terms = lexical_terms(query)
    if not terms:
        return output
    fts_query = " OR ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in dict.fromkeys(terms))
    index_path = safe_index_path(corpus, requested_index)

    started = time.perf_counter_ns()
    connection = sqlite3.connect(f"file:{index_path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT s.*
            FROM sections_fts AS f
            JOIN sections AS s ON s.ordinal = f.rowid
            WHERE sections_fts MATCH ?
            """,
            (fts_query,),
        ).fetchall()
    except sqlite3.DatabaseError as error:
        raise SearchError(f"lexical index query failed: {error}") from error
    finally:
        connection.close()

    query_normalized = normalize_search_text(query)
    ranked = []
    section_by_id = {section.stable_section_id: section for section in corpus.sections}
    for row in rows:
        score, ranking = score_candidate(query_normalized, terms, row)
        ranked.append((score, row["ordinal"], row, ranking))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    candidate_count = len(ranked)
    candidates = []
    for rank, (score, _ordinal, row, ranking) in enumerate(ranked[:limit], start=1):
        section = section_by_id[row["stable_section_id"]]
        candidate = candidate_base(section, row["searchable_text_character_count"])
        candidate.update(
            {
                "rank": rank,
                "deterministic_score": score,
                "ranking_metadata": ranking,
            }
        )
        candidates.append(candidate)
    elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
    output.update(
        {
            "status": "FOUND" if candidates else "NOT_FOUND",
            "result_count": len(candidates),
            "candidate_count": candidate_count,
            "query_latency_ms": round(elapsed_ms, 3),
            "candidates": candidates,
        }
    )
    return output


def print_human(result: dict[str, Any]) -> None:
    print(f"{result['retrieval_mode']} {result['status']} ({result['result_count']} returned)")
    for candidate in result["candidates"]:
        print(
            f"{candidate['rank']}. {candidate['citation']} — {candidate['heading']} "
            f"[{candidate['derived_file_path']}]"
        )


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build", help="validate the corpus and rebuild the derived FTS5 index")
    build.add_argument("--json", action="store_true", help="emit machine-readable JSON")

    exact = subparsers.add_parser("exact", help="resolve an exact Title 17 section or citation")
    exact.add_argument("query")
    exact.add_argument("--json", action="store_true", help="emit machine-readable JSON")

    search = subparsers.add_parser("search", help="run deterministic lexical candidate search")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=5)
    search.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    return parser.parse_args()


def main() -> int:
    args = arguments()
    try:
        corpus = load_corpus()
        if args.command == "build":
            metrics = build_index(corpus, reason="explicit")
            result = {"schema_version": OUTPUT_SCHEMA_VERSION, "operation": "BUILD", "build_metrics": metrics}
            if args.json:
                print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
            else:
                print(
                    f"built {metrics['section_count']} sections at {metrics['index_path']} "
                    f"in {metrics['build_wall_clock_ms']:.3f} ms ({metrics['generated_index_byte_size']} bytes)"
                )
            return 0
        result = exact_lookup(args.query, corpus) if args.command == "exact" else lexical_search(args.query, corpus, args.limit)
        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
        else:
            print_human(result)
        return 0
    except (OSError, KeyError, TypeError, json.JSONDecodeError, sqlite3.DatabaseError, SearchError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
