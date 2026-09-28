#!/usr/bin/env python3
"""Validate immutable public legal-v1 artifacts and optional committed evaluator gold."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

BENCHMARK_PATH = Path("eval/benchmark/legal/v1.json")
CONDITIONS_PATH = Path("eval/benchmark/legal/v1-conditions.json")
QUESTION_PATH = Path("eval/agent-visible/legal/v1/questions.jsonl")
EVALUATOR_ROOT = Path("eval/evaluator-only")
REVIEW_ROOT = Path(".pi-cache")
EXPECTED_BENCHMARK_ID = "legal-v1"
EXPECTED_STATUS = "FROZEN"
EXPECTED_FROZEN_AT = "2026-09-28T14:58:04Z"
EXPECTED_FROZEN_FROM_COMMIT = "4cc27017cb9de7223652b49528cf6be991dae606"
EXPECTED_QUESTION_SHA256 = "22337618074909dd9fec0e55877d838ddb68070aee1d937f2b602c057821087a"
EXPECTED_GOLD_SHA256 = "8aaa6e9bec3bf47285b8c2447f1d5599a682b01b5deb18487088d03b5d1a695d"
EXPECTED_CONDITIONS_SHA256 = "f1e783112f4f55963eee7b9a2a627de9d90a4b047054325a5eb95cf2e775b1c5"
EXPECTED_CORPUS_ID = "usc-title-17-119-111"
EXPECTED_CORPUS_SHA256 = "414324629847597bad94c750c76dfcb6a2ef4ed06ecbdc5ab38f59cee8d797ee"
EXPECTED_CANONICALIZATION = (
    "UTF-8 JSON Lines; one object per line; keys recursively sorted; separators ',' and ':'; "
    "ensure_ascii=false; LF after every line"
)
EXPECTED_CONDITIONS = ["EAGER", "PROGRESSIVE", "FORCED_RETRIEVAL_CONTROL"]
EXPECTED_CLASS_COUNTS = {
    "NO_LOOKUP": 4,
    "EXACT_CITATION": 4,
    "SINGLE_SECTION_NATURAL_LANGUAGE": 4,
    "MULTI_SECTION": 3,
    "FOLLOW_UP": 3,
    "OUT_OF_CORPUS_OR_INSUFFICIENT": 2,
}
LOOKUP_EXPECTATIONS = {
    "NOT_NEEDED",
    "REQUIRED",
    "CHECK_REQUIRED_TO_ESTABLISH_LIMITATION",
    "REUSE_OR_TARGETED",
}
RESPONSE_MODES = {"DIRECT_ANSWER", "SOURCE_GROUNDED_ANSWER", "CORPUS_LIMITATION"}
CORPUS_ANSWERABILITY = {"FULLY_ANSWERABLE", "PARTIALLY_ANSWERABLE", "NOT_ANSWERABLE"}
CASE_003_PROMPT = "Hi! How are you?"
CASE_014_PROMPT = (
    "An artist owns the copyright in a qualifying work of visual art and sells the sole physical "
    "canvas. The transaction expressly transfers only the physical object and does not transfer "
    "copyright ownership. Under Title 17, distinguish ownership of the canvas from ownership of "
    "copyright, and identify the relevant economic and attribution/integrity rights that remain "
    "with the artist."
)


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

    if metadata.get("schema_version") != 1 or metadata.get("benchmark_id") != EXPECTED_BENCHMARK_ID:
        raise ValidationError("unexpected frozen benchmark schema version or ID")
    if metadata.get("status") != EXPECTED_STATUS:
        raise ValidationError(f"benchmark status must remain {EXPECTED_STATUS}")
    if metadata.get("frozen_at_utc") != EXPECTED_FROZEN_AT:
        raise ValidationError("frozen timestamp must not change")
    if metadata.get("frozen_from_commit") != EXPECTED_FROZEN_FROM_COMMIT:
        raise ValidationError("frozen source commit must not change")
    if metadata.get("owner_review_complete") is not True:
        raise ValidationError("owner review must remain complete")
    if metadata.get("class_counts") != EXPECTED_CLASS_COUNTS:
        raise ValidationError("class counts do not match frozen legal-v1")
    execution = metadata.get("execution")
    if execution != {"live_runs_authorized": False, "results_exist": False}:
        raise ValidationError("freezing must not authorize a live run or claim results")

    question_metadata = metadata.get("question_set", {})
    if question_metadata.get("path") != QUESTION_PATH.as_posix():
        raise ValidationError("question path does not match frozen legal-v1")
    if question_metadata.get("sha256") != EXPECTED_QUESTION_SHA256:
        raise ValidationError("declared question SHA-256 differs from frozen legal-v1")
    if question_metadata.get("case_count") != 20 or question_metadata.get("turn_count") != 23:
        raise ValidationError("question metadata must declare 20 cases and 23 turns")
    if question_metadata.get("byte_identical_to_reviewed_draft") is not True:
        raise ValidationError("question set must remain byte-identical to the reviewed draft")
    actual_question_hash = sha256(root / QUESTION_PATH)
    if actual_question_hash != EXPECTED_QUESTION_SHA256:
        raise ValidationError("question bytes differ from frozen legal-v1")

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
    if questions[2]["turns"][0]["prompt"] != CASE_003_PROMPT:
        raise ValidationError("case 003 must be the approved casual-conversation prompt")
    if questions[13]["turns"][0]["prompt"] != CASE_014_PROMPT:
        raise ValidationError("case 014 must contain the approved ownership and transfer stipulations")

    if sha256(root / CONDITIONS_PATH) != EXPECTED_CONDITIONS_SHA256:
        raise ValidationError("condition specification bytes differ from frozen legal-v1")
    if conditions.get("schema_version") != 1 or conditions.get("benchmark_id") != EXPECTED_BENCHMARK_ID:
        raise ValidationError("unexpected frozen conditions schema version or benchmark ID")
    if conditions.get("status") != EXPECTED_STATUS:
        raise ValidationError(f"conditions status must remain {EXPECTED_STATUS}")
    condition_values = conditions.get("conditions")
    if not isinstance(condition_values, list):
        raise ValidationError("conditions must be an array")
    condition_ids = [value.get("condition_id") for value in condition_values if isinstance(value, dict)]
    if condition_ids != EXPECTED_CONDITIONS:
        raise ValidationError(f"condition IDs must be {EXPECTED_CONDITIONS}")
    forced = condition_values[2]
    if forced.get("forced_lookup_expectations") != [
        "REQUIRED",
        "CHECK_REQUIRED_TO_ESTABLISH_LIMITATION",
    ]:
        raise ValidationError("forced control must force both required lookup classifications")
    if forced.get("not_forced_lookup_expectations") != ["NOT_NEEDED"]:
        raise ValidationError("forced control must not force NOT_NEEDED turns")
    if not isinstance(forced.get("reuse_or_targeted_policy"), str):
        raise ValidationError("forced control must preserve the REUSE_OR_TARGETED policy")

    follow_up = conditions.get("follow_up_methodology", {})
    if follow_up.get("design") != "END_TO_END_CONVERSATIONAL":
        raise ValidationError("follow-up design must be end-to-end conversational")
    if follow_up.get("prior_assistant_context_may_differ_across_conditions") is not True:
        raise ValidationError("follow-up methodology must permit differing prior assistant context")
    if follow_up.get("measurements") != ["PER_TURN", "CASE_CONVERSATION_LEVEL"]:
        raise ValidationError("follow-up methodology must require turn and conversation measurements")
    if follow_up.get("t2_is_identical_input_paired_ab") is not False:
        raise ValidationError("follow-up t2 must not be treated as an identical-input paired A/B")
    if "separate benchmark/version" not in follow_up.get("isolated_follow_up_policy", ""):
        raise ValidationError("isolated follow-ups must require a separate benchmark/version")
    if "actual agent response" not in follow_up.get("sequence", ""):
        raise ValidationError("follow-up sequence must include each condition's actual t1 response")
    if metadata.get("conditions_path") != CONDITIONS_PATH.as_posix():
        raise ValidationError("conditions path does not match the public contract")

    corpus = metadata.get("corpus", {})
    source_manifest = read_json(root / "corpus/manifest/title17.json")
    sections_manifest = read_json(root / "corpus/manifest/title17-sections.json")
    if corpus.get("corpus_id") != EXPECTED_CORPUS_ID:
        raise ValidationError("benchmark corpus ID differs from frozen legal-v1")
    if corpus.get("source_xml_sha256") != EXPECTED_CORPUS_SHA256:
        raise ValidationError("benchmark corpus checksum differs from frozen legal-v1")
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
    if commitment.get("canonicalization") != EXPECTED_CANONICALIZATION:
        raise ValidationError("gold canonicalization rule differs from frozen legal-v1")
    if commitment.get("sha256") != EXPECTED_GOLD_SHA256:
        raise ValidationError("gold commitment differs from frozen legal-v1")

    commit_reveal = metadata.get("commit_reveal", {})
    if commit_reveal.get("status") != "COMMITTED_NOT_REVEALED":
        raise ValidationError("commit–reveal status must remain committed and unrevealed")
    if commit_reveal.get("gold_published") is not False or commit_reveal.get("reveal_authorized") is not False:
        raise ValidationError("private gold must remain unpublished and unrevealed")
    attestations = metadata.get("freeze_attestations", {})
    expected_attestations = {
        "questions_frozen_before_any_benchmark_retrieval_execution": True,
        "benchmark_frozen_before_any_model_evaluation": True,
        "lexical_baseline_not_run_against_benchmark_questions_before_freeze": True,
        "benchmark_retrieval_executions_before_freeze": 0,
        "model_evaluation_calls_before_freeze": 0,
        "embedding_calls_before_freeze": 0,
    }
    if attestations != expected_attestations:
        raise ValidationError("freeze attestations differ from frozen legal-v1")

    result_files = [
        path for path in (root / "results").rglob("*")
        if path.is_file() and path.name != ".gitkeep"
    ]
    if result_files:
        raise ValidationError("benchmark results exist even though legal-v1 is unexecuted")
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
    if sha256(candidate) != EXPECTED_GOLD_SHA256:
        raise ValidationError("evaluator gold does not match frozen legal-v1 commitment")
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
            base_keys = {
                "answer_criteria",
                "expected_sections",
                "lookup_expectation",
                "response_mode",
                "turn_id",
                "unsupported_claim_risks",
            }
            actual_keys = set(expected)
            if actual_keys not in (base_keys, base_keys | {"corpus_answerability"}):
                raise ValidationError(
                    f"{label} turn {turn_ordinal} keys differ: got {sorted(actual_keys)}"
                )
            if expected["turn_id"] != public["turn_id"]:
                raise ValidationError(f"gold/public turn ID mismatch for {question_id}")
            if expected["lookup_expectation"] not in LOOKUP_EXPECTATIONS:
                raise ValidationError(f"invalid lookup expectation for {expected['turn_id']}")
            if expected["response_mode"] not in RESPONSE_MODES:
                raise ValidationError(f"invalid response mode for {expected['turn_id']}")
            if (
                "corpus_answerability" in expected
                and expected["corpus_answerability"] not in CORPUS_ANSWERABILITY
            ):
                raise ValidationError(f"invalid corpus answerability for {expected['turn_id']}")
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

            if case_class == "NO_LOOKUP":
                if sections or expected["lookup_expectation"] != "NOT_NEEDED":
                    raise ValidationError("NO_LOOKUP must not require corpus sections")
            elif case_class == "OUT_OF_CORPUS_OR_INSUFFICIENT":
                lookup = expected["lookup_expectation"]
                if lookup == "NOT_NEEDED":
                    if sections:
                        raise ValidationError("NOT_NEEDED limitation cases must not name sections")
                elif lookup == "CHECK_REQUIRED_TO_ESTABLISH_LIMITATION":
                    if not sections or expected.get("corpus_answerability") != "PARTIALLY_ANSWERABLE":
                        raise ValidationError(
                            "checked limitation cases require supporting sections and partial answerability"
                        )
                else:
                    raise ValidationError("invalid lookup expectation for limitation case")
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

    case003 = gold[2]
    if case003["case_class"] != "NO_LOOKUP":
        raise ValidationError("case 003 must remain NO_LOOKUP")
    case014 = gold[13]["turn_expectations"][0]
    if case014["expected_sections"] != ["17-usc-106", "17-usc-106a", "17-usc-202"]:
        raise ValidationError("case 014 must remain bounded to §§ 106, 106A, and 202")
    case019 = gold[18]["turn_expectations"][0]
    if (
        case019["lookup_expectation"] != "CHECK_REQUIRED_TO_ESTABLISH_LIMITATION"
        or case019["expected_sections"] != ["17-usc-708"]
        or case019.get("corpus_answerability") != "PARTIALLY_ANSWERABLE"
    ):
        raise ValidationError("case 019 must use the checked § 708 partial-answerability contract")
    return gold


def render_review(
    metadata: dict[str, Any], questions: list[dict[str, Any]], gold: list[dict[str, Any]]
) -> str:
    lines = [
        "# Legal benchmark v1 — frozen local review packet",
        "",
        "> LOCAL EVALUATOR-ONLY MATERIAL. DO NOT COMMIT OR EXPOSE TO AN AGENT.",
        "",
        f"Status: `{metadata['status']}` (frozen; live runs are not authorized)",
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
                    *(
                        [f"**Corpus answerability:** `{expected['corpus_answerability']}`"]
                        if "corpus_answerability" in expected
                        else []
                    ),
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
        message = f"validated frozen legal-v1: {len(questions)} cases"
        if args.review_output is not None and args.gold is None:
            raise ValidationError("--review-output requires --gold")
        if args.gold is not None:
            gold = validate_gold(root, metadata, questions, args.gold)
            message += f"; verified unchanged committed gold: {len(gold)} cases"
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
