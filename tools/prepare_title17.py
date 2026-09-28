#!/usr/bin/env python3
"""Deterministically extract statutory Title 17 sections from pinned USLM XML."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
import xml.etree.ElementTree as ET

TOOL_VERSION = "1"
USLM_NS = "http://xml.house.gov/schemas/uslm/1.0"
DC_NS = "http://purl.org/dc/elements/1.1/"
DCTERMS_NS = "http://purl.org/dc/terms/"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
NS = {"u": USLM_NS, "dc": DC_NS}
STATUTORY_IDENTIFIER = re.compile(r"^/us/usc/t17/s([A-Za-z0-9-]+)$")

ET.register_namespace("", USLM_NS)
ET.register_namespace("xsi", XSI_NS)
ET.register_namespace("dc", DC_NS)
ET.register_namespace("dcterms", DCTERMS_NS)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalized_text(element: ET.Element | None) -> str:
    if element is None:
        return ""
    return " ".join("".join(element.itertext()).split())


def parse_xml(path: Path) -> ET.ElementTree:
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True))
    return ET.parse(path, parser=parser)


def load_source_manifest(path: Path, source: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    expected = data["xml"]
    if source.name != expected["filename"]:
        raise ValueError(f"source filename is not pinned: {source.name}")
    if source.stat().st_size != expected["byte_size"]:
        raise ValueError("source XML byte size does not match source manifest")
    if sha256(source) != expected["sha256"]:
        raise ValueError("source XML SHA-256 does not match source manifest")
    return data


def extract(
    source: Path,
    source_manifest_path: Path,
    output_dir: Path,
    derived_manifest_path: Path,
    generated_at: str | None = None,
) -> dict:
    source_data = load_source_manifest(source_manifest_path, source)
    tree = parse_xml(source)
    root = tree.getroot()

    doc_number = normalized_text(root.find("./u:meta/u:docNumber", NS))
    dc_title = normalized_text(root.find("./u:meta/dc:title", NS))
    if root.get("identifier") != "/us/usc/t17" or doc_number != "17" or dc_title != "Title 17":
        raise ValueError("source XML does not identify U.S. Code Title 17")

    sections: list[tuple[str, ET.Element]] = []
    for element in root.findall(".//u:section", NS):
        identifier = element.get("identifier", "")
        match = STATUTORY_IDENTIFIER.fullmatch(identifier)
        if match:
            sections.append((match.group(1), element))
    if not sections:
        raise ValueError("no statutory Title 17 sections found")

    numbers = [number for number, _ in sections]
    identifiers = [element.get("identifier") for _, element in sections]
    if len(numbers) != len(set(numbers)) or len(identifiers) != len(set(identifiers)):
        raise ValueError("statutory section numbers or identifiers are not unique")

    temporary = output_dir.with_name(output_dir.name + ".tmp")
    if temporary.exists():
        shutil.rmtree(temporary)
    temporary.mkdir(parents=True)

    entries = []
    try:
        for number, element in sections:
            stable_id = f"17-usc-{number.lower()}"
            filename = f"{stable_id}.xml"
            destination = temporary / filename

            section_copy = copy.deepcopy(element)
            section_copy.tail = None
            payload = ET.tostring(
                section_copy,
                encoding="utf-8",
                xml_declaration=True,
                short_empty_elements=True,
            ) + b"\n"
            destination.write_bytes(payload)

            entries.append(
                {
                    "stable_section_id": stable_id,
                    "citation": f"17 U.S.C. § {number}",
                    "section_number": number,
                    "heading": normalized_text(element.find("u:heading", NS)),
                    "derived_file_path": f"corpus/sections/title17/{filename}",
                    "source_xml_path": source_data["xml"]["repository_path"],
                    "source_xml_sha256": source_data["xml"]["sha256"],
                    "source_xml_element_id": element.get("id"),
                    "source_xml_identifier": element.get("identifier"),
                    "sha256": sha256(destination),
                }
            )

        if output_dir.exists():
            shutil.rmtree(output_dir)
        temporary.replace(output_dir)
    except BaseException:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise

    if generated_at is None:
        generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    manifest = {
        "schema_version": 1,
        "corpus_id": source_data["corpus_id"],
        "title_number": 17,
        "source_xml_path": source_data["xml"]["repository_path"],
        "source_xml_sha256": source_data["xml"]["sha256"],
        "extraction_tool": "tools/prepare_title17.py",
        "extraction_tool_version": TOOL_VERSION,
        "generated_at_utc": generated_at,
        "total_section_count": len(entries),
        "boundary": (
            "Includes each USLM <section> whose identifier is exactly under /us/usc/t17/s*. "
            "Each file preserves that complete section subtree, including statutory hierarchy, "
            "source credits, and section-local notes. Excludes title/chapter tables of contents, "
            "metadata, title/chapter notes outside sections, and nested quoted Act sections that "
            "lack a Title 17 statutory identifier. The pinned source XML remains authoritative."
        ),
        "normalization": (
            "No legal text is paraphrased or whitespace-normalized. Python ElementTree performs "
            "deterministic XML reserialization; the section's out-of-scope tail whitespace is removed, "
            "an XML declaration and final newline are emitted, and namespace declarations may be relocated."
        ),
        "sections": entries,
    }
    derived_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    derived_manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return manifest


def validate(manifest_path: Path) -> None:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    repository_root = manifest_path.resolve().parents[2]
    entries = data["sections"]
    if data["total_section_count"] != len(entries) or not entries:
        raise ValueError("derived manifest has an invalid section count")
    ids = [entry["stable_section_id"] for entry in entries]
    citations = [entry["citation"] for entry in entries]
    if len(ids) != len(set(ids)) or len(citations) != len(set(citations)):
        raise ValueError("derived section IDs or citations are not unique")

    source = (repository_root / data["source_xml_path"]).resolve(strict=True)
    try:
        source.relative_to(repository_root)
    except ValueError as error:
        raise ValueError("source XML path escapes repository") from error
    if sha256(source) != data["source_xml_sha256"]:
        raise ValueError("pinned source XML checksum mismatch")
    source_root = parse_xml(source).getroot()
    if source_root.get("identifier") != "/us/usc/t17":
        raise ValueError("pinned source does not identify Title 17")
    source_sections = {
        (element.get("identifier"), element.get("id"))
        for element in source_root.findall(".//u:section", NS)
    }

    for entry in entries:
        path = (repository_root / entry["derived_file_path"]).resolve(strict=True)
        try:
            path.relative_to(repository_root)
        except ValueError as error:
            raise ValueError(f"derived path escapes repository: {path}") from error
        if not path.is_file():
            raise ValueError(f"missing derived section: {path}")
        if sha256(path) != entry["sha256"]:
            raise ValueError(f"checksum mismatch: {path}")
        section_root = parse_xml(path).getroot()
        source_identity = (entry["source_xml_identifier"], entry["source_xml_element_id"])
        if section_root.get("identifier") != entry["source_xml_identifier"]:
            raise ValueError(f"source trace mismatch: {path}")
        if source_identity not in source_sections:
            raise ValueError(f"section is not traceable to pinned source: {path}")
        if entry["source_xml_sha256"] != data["source_xml_sha256"]:
            raise ValueError(f"source identity mismatch: {path}")


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("corpus/source/title17/usc17.xml"))
    parser.add_argument("--source-manifest", type=Path, default=Path("corpus/manifest/title17.json"))
    parser.add_argument("--output", type=Path, default=Path("corpus/sections/title17"))
    parser.add_argument("--manifest", type=Path, default=Path("corpus/manifest/title17-sections.json"))
    parser.add_argument("--generated-at", help="UTC generation timestamp (used for reproducible rebuilds)")
    parser.add_argument("--validate-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = arguments()
    try:
        if not args.validate_only:
            result = extract(
                args.source,
                args.source_manifest,
                args.output,
                args.manifest,
                args.generated_at,
            )
            print(f"extracted {result['total_section_count']} sections")
        validate(args.manifest)
        print("validation passed")
        return 0
    except (OSError, ET.ParseError, KeyError, ValueError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
