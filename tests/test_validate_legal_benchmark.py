from __future__ import annotations

import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.validate_legal_benchmark import (
    CASE_003_PROMPT,
    CASE_014_PROMPT,
    CONDITIONS_PATH,
    EXPECTED_CLASS_COUNTS,
    ValidationError,
    read_json,
    read_jsonl,
    validate_public,
)

ROOT = Path(__file__).resolve().parents[1]


class ValidateLegalBenchmarkTests(unittest.TestCase):
    def test_public_draft_has_the_declared_shape_offline(self) -> None:
        with mock.patch.object(socket, "socket", side_effect=AssertionError("network attempted")):
            metadata, questions = validate_public(ROOT)
        self.assertEqual(metadata["status"], "DRAFT_OWNER_REVIEW")
        self.assertEqual(metadata["target_class_counts"], EXPECTED_CLASS_COUNTS)
        self.assertEqual(len(questions), 20)
        self.assertEqual(sum(len(case["turns"]) for case in questions), 23)

    def test_owner_review_question_wording_is_exact(self) -> None:
        _, questions = validate_public(ROOT)
        self.assertEqual(questions[2]["turns"][0]["prompt"], CASE_003_PROMPT)
        self.assertEqual(questions[13]["turns"][0]["prompt"], CASE_014_PROMPT)

    def test_forced_control_and_follow_up_methodology_are_explicit(self) -> None:
        validate_public(ROOT)
        conditions = read_json(ROOT / CONDITIONS_PATH)
        forced = conditions["conditions"][2]
        self.assertEqual(
            forced["forced_lookup_expectations"],
            ["REQUIRED", "CHECK_REQUIRED_TO_ESTABLISH_LIMITATION"],
        )
        self.assertEqual(forced["not_forced_lookup_expectations"], ["NOT_NEEDED"])
        follow_up = conditions["follow_up_methodology"]
        self.assertEqual(follow_up["design"], "END_TO_END_CONVERSATIONAL")
        self.assertEqual(follow_up["measurements"], ["PER_TURN", "CASE_CONVERSATION_LEVEL"])
        self.assertFalse(follow_up["t2_is_identical_input_paired_ab"])

    def test_agent_visible_rows_contain_no_evaluator_fields(self) -> None:
        _, questions = validate_public(ROOT)
        forbidden = {
            "case_class",
            "expected_lookup",
            "lookup_expectation",
            "expected_sections",
            "answer_criteria",
            "gold",
            "rubric",
        }
        for case in questions:
            self.assertTrue(forbidden.isdisjoint(case))
            for turn in case["turns"]:
                self.assertTrue(forbidden.isdisjoint(turn))

    def test_noncanonical_private_jsonl_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "gold.jsonl"
            path.write_text(json.dumps({"z": 1, "a": 2}) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValidationError, "noncanonical evaluator gold"):
                read_jsonl(path, require_canonical=True)

    def test_private_jsonl_requires_final_lf(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "gold.jsonl"
            path.write_text('{"a":1}', encoding="utf-8")
            with self.assertRaisesRegex(ValidationError, "must end with LF"):
                read_jsonl(path, require_canonical=True)


if __name__ == "__main__":
    unittest.main()
