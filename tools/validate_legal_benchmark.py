#!/usr/bin/env python3
"""Validate the public legal benchmark draft and optional committed evaluator gold."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

BENCHMARK_PATH = Path("eval/benchmark/legal/v1-draft.json")
CONDITIONS_PATH = Path("eval/benchmark/legal/v1-draft-conditions.json")
QUESTION_PATH = Path("eval/agent-visible/legal/v1-draft/questions.jsonl")
EVALUATOR_ROOT = Path("eval/evaluator-only")
REVIEW_ROOT = Path(".pi-cache")
EXPECTED_STATUS = "DRAFT_OWNER_REVIEW"
EXPECTED_CONDITIONS = ["EAGER", "PROGRESSIVE", "FORCED_RETRIEVAL_CONTROL"]
EXPECTED_CLASS_COUNTS = {
    "NO_LOOKUP": 4,
    "EXACT_CITATION": 4,
    "SINGLE_SECTION_NATURAL_LANGUAGE": 4,
    "MULTI_SECTION": 3,
    "FOLLOW_UP": 3,
    "OUT_OF_CORPUS_OR_INSUFFICIENT": 2,
}
LOOKUP_EXPECTATIONS = {"NOT_NEEDED", "REQUIRED", "REUSE_OR_TARGETED"}
RESPONSE_MODES = {"DIRECT_ANSWER", "SOURCE_GROUNDED_ANSWER", "CORPUS_LIMITATION"}


class ValidationError(ValueError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ValidationError(
            f"{label} keys differ: expected {sorted(expected)}, got {sorted(value)}"
        )


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValidationError(f"cannot read JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise ValidationError(f"JSON root must be an object: {path}")
    return value


def read_jsonl(path: Path, *, require_canonical: bool = False) -> list[dict[str, Any]]:
    try:
        payload = path.read_bytes()
        text = payload.decode("utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise ValidationError(f"cannot read UTF-8 JSONL {path}: {error}") from error
    if not payload.endswith(b"\n"):
        raise ValidationError(f"JSONL must end with LF: {path}")
    if b"\r" in payload:
        raise ValidationError(f"JSONL must use LF, not CRLF: {path}")

    values: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line:
            raise ValidationError(f"blank JSONL line at {path}:{line_number}")
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValidationError(f"invalid JSON at {path}:{line_number}: {error}") from error
        if not isinstance(value, dict):
            raise ValidationError(f"JSONL value must be an object at {path}:{line_number}")
        if require_canonical:
            canonical = json.dumps(
                value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            )
            if line != canonical:
                raise ValidationError(f"noncanonical evaluator gold at {path}:{line_number}")
        values.append(value)
    return values


def validate_public(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    root = root.resolve(strict=True)
    metadata = read_json(root / BENCHMARK_PATH)
    conditions = read_json(root / CONDITIONS_PATH)
    questions = read_jsonl(root / QUESTION_PATH)

    if metadata.get("schema_version") != 1 or metadata.get("benchmark_id") != "legal-v1-draft":
        raise ValidationError("unexpected benchmark schema version or ID")
    if metadata.get("status") != EXPECTED_STATUS:
        raise ValidationError(f"benchmark status must remain {EXPECTED_STATUS}")
    if metadata.get("target_class_counts") != EXPECTED_CLASS_COUNTS:
        raise ValidationError("target class counts do not match the approved 20-case shape")
    execution = metadata.get("execution")
    if execution != {"live_runs_authorized": False, "frozen": False, "results_exist": False}:
        raise ValidationError("draft execution flags must remain false")

    question_metadata = metadata.get("question_set", {})
    if question_metadata.get("path") != QUESTION_PATH.as_posix():
        raise ValidationError("question path does not match the public contract")
    if question_metadata.get("case_count") != 20 or question_metadata.get("turn_count") != 23:
        raise ValidationError("question metadata must declare 20 cases and 23 turns")
    actual_question_hash = sha256(root / QUESTION_PATH)
    if question_metadata.get("sha256") != actual_question_hash:
        raise ValidationError("question-set SHA-256 does not match its bytes")

    if len(questions) != 20:
        raise ValidationError(f"expected 20 questions, found {len(questions)}")
    total_turns = 0
    two_turn_cases = 0
    for ordinal, question in enumerate(questions, start=1):
        label = f"question {ordinal}"
        require_keys(question, {"question_id", "turns"}, label)
        expected_id = f"legal-v1-draft-{ordinal:03d}"
        if question["question_id"] != expected_id:
            raise ValidationError(f"{label} must have ID {expected_id}")
        turns = question["turns"]
        if not isinstance(turns, list) or len(turns) not in (1, 2):
            raise ValidationError(f"{expected_id} must contain one or two turns")
        if len(turns) == 2:
            two_turn_cases += 1
        total_turns += len(turns)
        for turn_ordinal, turn in enumerate(turns, start=1):
            require_keys(turn, {"turn_id", "prompt"}, f"{expected_id} turn {turn_ordinal}")
            expected_turn_id = f"{expected_id}-t{turn_ordinal}"
            if turn["turn_id"] != expected_turn_id:
                raise ValidationError(f"turn ID must be {expected_turn_id}")
            if not isinstance(turn["prompt"], str) or not turn["prompt"].strip():
                raise ValidationError(f"prompt must be nonempty: {expected_turn_id}")
    if total_turns != 23 or two_turn_cases != 3:
        raise ValidationError("public set must contain 23 turns and exactly three two-turn cases")

    if conditions.get("schema_version") != 1 or conditions.get("benchmark_id") != "legal-v1-draft":
        raise ValidationError("unexpected conditions schema version or benchmark ID")
    if conditions.get("status") != EXPECTED_STATUS:
        raise ValidationError(f"conditions status must remain {EXPECTED_STATUS}")
    condition_values = conditions.get("conditions")
    if not isinstance(condition_values, list):
        raise ValidationError("conditions must be an array")
    condition_ids = [value.get("condition_id") for value in condition_values if isinstance(value, dict)]
    if condition_ids != EXPECTED_CONDITIONS:
        raise ValidationError(f"condition IDs must be {EXPECTED_CONDITIONS}")
    if metadata.get("conditions_path") != CONDITIONS_PATH.as_posix():
        raise ValidationError("conditions path does not match the public contract")

    corpus = metadata.get("corpus", {})
    source_manifest = read_json(root / "corpus/manifest/title17.json")
    sections_manifest = read_json(root / "corpus/manifest/title17-sections.json")
    if corpus.get("corpus_id") != source_manifest.get("corpus_id"):
        raise ValidationError("benchmark corpus ID differs from pinned source manifest")
    if corpus.get("source_xml_sha256") != source_manifest.get("xml", {}).get("sha256"):
        raise ValidationError("benchmark source checksum differs from pinned source manifest")
    if corpus.get("source_xml_sha256") != sections_manifest.get("source_xml_sha256"):
        raise ValidationError("benchmark source checksum differs from section manifest")
    source_path = root / corpus.get("source_xml_path", "")
    if not source_path.is_file() or sha256(source_path) != corpus.get("source_xml_sha256"):
        raise ValidationError("benchmark source XML is missing or has the wrong checksum")

    commitment = metadata.get("gold_commitment", {})
    if commitment.get("algorithm") != "sha256":
        raise ValidationError("gold commitment algorithm must be sha256")
    digest = commitment.get("sha256")
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValidationError("gold commitment must be a lowercase SHA-256 digest")
    return metadata, questions


def validate_gold(
    root: Path,
    metadata: dict[str, Any],
    questions: list[dict[str, Any]],
    gold_path: Path,
) -> list[dict[str, Any]]:
    root = root.resolve(strict=True)
    candidate = gold_path if gold_path.is_absolute() else root / gold_path
    candidate = candidate.resolve(strict=True)
    evaluator_root = (root / EVALUATOR_ROOT).resolve()
    if not candidate.is_relative_to(evaluator_root):
        raise ValidationError("gold must be under eval/evaluator-only")
    gold = read_jsonl(candidate, require_canonical=True)
    if sha256(candidate) != metadata["gold_commitment"]["sha256"]:
        raise ValidationError("evaluator gold does not match the public SHA-256 commitment")
    if len(gold) != len(questions):
        raise ValidationError("gold and question case counts differ")

    section_manifest = read_json(root / "corpus/manifest/title17-sections.json")
    known_sections = {item["stable_section_id"] for item in section_manifest["sections"]}
    class_counts: Counter[str] = Counter()
    question_by_id = {value["question_id"]: value for value in questions}

    for ordinal, case in enumerate(gold, start=1):
        label = f"gold case {ordinal}"
        require_keys(case, {"case_class", "question_id", "turn_expectations"}, label)
        question_id = f"legal-v1-draft-{ordinal:03d}"
        if case["question_id"] != question_id:
            raise ValidationError(f"{label} must have ID {question_id}")
        case_class = case["case_class"]
        if case_class not in EXPECTED_CLASS_COUNTS:
            raise ValidationError(f"unknown case class in {label}: {case_class}")
        class_counts[case_class] += 1

        expected_turns = case["turn_expectations"]
        public_turns = question_by_id[question_id]["turns"]
        if not isinstance(expected_turns, list) or len(expected_turns) != len(public_turns):
            raise ValidationError(f"turn count differs for {question_id}")
        if (case_class == "FOLLOW_UP") != (len(expected_turns) == 2):
            raise ValidationError("exactly FOLLOW_UP cases must contain two turns")

        for turn_ordinal, (expected, public) in enumerate(zip(expected_turns, public_turns), start=1):
            require_keys(
                expected,
                {
                    "answer_criteria",
                    "expected_sections",
                    "lookup_expectation",
                    "response_mode",
                    "turn_id",
                    "unsupported_claim_risks",
                },
                f"{label} turn {turn_ordinal}",
            )
            if expected["turn_id"] != public["turn_id"]:
                raise ValidationError(f"gold/public turn ID mismatch for {question_id}")
            if expected["lookup_expectation"] not in LOOKUP_EXPECTATIONS:
                raise ValidationError(f"invalid lookup expectation for {expected['turn_id']}")
            if expected["response_mode"] not in RESPONSE_MODES:
                raise ValidationError(f"invalid response mode for {expected['turn_id']}")
            if not isinstance(expected["answer_criteria"], list) or not expected["answer_criteria"]:
                raise ValidationError(f"answer criteria must be a nonempty list for {expected['turn_id']}")
            if not isinstance(expected["unsupported_claim_risks"], list):
                raise ValidationError(f"unsupported-claim risks must be a list for {expected['turn_id']}")
            sections = expected["expected_sections"]
            if not isinstance(sections, list) or len(sections) != len(set(sections)):
                raise ValidationError(f"expected sections must be a unique list for {expected['turn_id']}")
            unknown = set(sections) - known_sections
            if unknown:
                raise ValidationError(f"unknown expected sections for {expected['turn_id']}: {sorted(unknown)}")

            if case_class in {"NO_LOOKUP", "OUT_OF_CORPUS_OR_INSUFFICIENT"}:
                if sections or expected["lookup_expectation"] != "NOT_NEEDED":
                    raise ValidationError(f"{case_class} must not require corpus sections")
            else:
                if not sections:
                    raise ValidationError(f"{case_class} must identify expected sections")
                expected_lookup = "REUSE_OR_TARGETED" if turn_ordinal == 2 else "REQUIRED"
                if expected["lookup_expectation"] != expected_lookup:
                    raise ValidationError(f"wrong lookup expectation for {expected['turn_id']}")

        union = set().union(*(set(turn["expected_sections"]) for turn in expected_turns))
        if case_class in {"EXACT_CITATION", "SINGLE_SECTION_NATURAL_LANGUAGE", "FOLLOW_UP"} and len(union) != 1:
            raise ValidationError(f"{case_class} must resolve to exactly one section per case")
        if case_class == "MULTI_SECTION" and len(union) < 2:
            raise ValidationError("MULTI_SECTION must resolve to at least two sections")

    if dict(class_counts) != EXPECTED_CLASS_COUNTS:
        raise ValidationError(
            f"gold class counts differ: expected {EXPECTED_CLASS_COUNTS}, got {dict(class_counts)}"
        )
    return gold


def render_review(
    metadata: dict[str, Any], questions: list[dict[str, Any]], gold: list[dict[str, Any]]
) -> str:
    lines = [
        "# Legal benchmark v1 draft — owner review packet",
        "",
        "> LOCAL EVALUATOR-ONLY MATERIAL. DO NOT COMMIT OR EXPOSE TO AN AGENT.",
        "",
        f"Status: `{metadata['status']}` (not frozen; live runs are not authorized)",
        f"Gold commitment: `{metadata['gold_commitment']['sha256']}`",
        "",
    ]
    gold_by_id = {case["question_id"]: case for case in gold}
    for question in questions:
        case = gold_by_id[question["question_id"]]
        lines.extend([f"## {question['question_id']} — {case['case_class']}", ""])
        expected_by_turn = {turn["turn_id"]: turn for turn in case["turn_expectations"]}
        for turn in question["turns"]:
            expected = expected_by_turn[turn["turn_id"]]
            lines.extend(
                [
                    f"### {turn['turn_id']}",
                    "",
                    f"**Question:** {turn['prompt']}",
                    "",
                    f"**Lookup:** `{expected['lookup_expectation']}`",
                    f"**Response mode:** `{expected['response_mode']}`",
                    f"**Expected sections:** {', '.join(expected['expected_sections']) or '(none)' }",
                    "",
                    "**Answer criteria:**",
                    *[f"- {item}" for item in expected["answer_criteria"]],
                    "",
                    "**Unsupported-claim risks:**",
                    *([f"- {item}" for item in expected["unsupported_claim_risks"]] or ["- (none)"]),
                    "",
                ]
            )
    return "\n".join(lines).rstrip() + "\n"


def write_review(root: Path, output: Path, content: str) -> Path:
    root = root.resolve(strict=True)
    candidate = output if output.is_absolute() else root / output
    resolved_parent = candidate.parent.resolve()
    review_root = (root / REVIEW_ROOT).resolve()
    if not resolved_parent.is_relative_to(review_root):
        raise ValidationError("review output must be under .pi-cache")
    if candidate.exists() and candidate.is_symlink():
        raise ValidationError("review output may not be a symlink")
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_text(content, encoding="utf-8")
    return candidate


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", type=Path, help="ignored evaluator gold to verify")
    parser.add_argument("--review-output", type=Path, help="ignored .pi-cache review packet")
    return parser.parse_args()


def main() -> int:
    args = arguments()
    root = Path(__file__).resolve().parents[1]
    try:
        metadata, questions = validate_public(root)
        message = f"validated public draft: {len(questions)} cases"
        if args.review_output is not None and args.gold is None:
            raise ValidationError("--review-output requires --gold")
        if args.gold is not None:
            gold = validate_gold(root, metadata, questions, args.gold)
            message += f"; verified committed gold: {len(gold)} cases"
            if args.review_output is not None:
                output = write_review(root, args.review_output, render_review(metadata, questions, gold))
                message += f"; wrote local review packet: {output.relative_to(root)}"
        print(message)
        return 0
    except (OSError, ValidationError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
