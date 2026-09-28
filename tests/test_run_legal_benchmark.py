from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import socket
import subprocess
import unittest
import uuid
from pathlib import Path
from unittest import mock

from tools.build_agent_workspace import WorkspaceError, build_workspace
from tools.run_legal_benchmark import (
    CONFIG, DRY_ROOT, GENERIC_LOOKUP, GOLD, INCLUDES, LIVE_BLOCK, LIVE_ROOT,
    ROOT, RunError, checked_read, control_instruction, initial_disclosure,
    load_config, main, output_root, run_fake,
)
from tools.validate_legal_benchmark import (
    EXPECTED_CONDITIONS, EXPECTED_CORPUS_SHA256, EXPECTED_QUESTION_SHA256,
    ValidationError, validate_public,
)


class LegalRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.created: list[Path] = []
        cls.results_before = list((ROOT / "results/raw").rglob("*"))

    @classmethod
    def tearDownClass(cls) -> None:
        for path in cls.created:
            shutil.rmtree(path, ignore_errors=True)
        assert list((ROOT / "results/raw").rglob("*")) == cls.results_before

    @classmethod
    def fake(cls, conditions: list[str]) -> dict:
        name = "test-" + uuid.uuid4().hex
        target = DRY_ROOT / name
        cls.created.append(target)
        # Calls to the real search tool and outbound sockets are forbidden in tests.
        original_run = subprocess.run

        def checked_subprocess(args, *a, **kw):
            if args[0] != "git":
                raise AssertionError("unexpected subprocess / benchmark retrieval")
            return original_run(args, *a, **kw)

        environment = {k: v for k, v in os.environ.items() if not k.endswith("_API_KEY")}
        with mock.patch.object(socket, "socket", side_effect=AssertionError("network attempted")), \
             mock.patch("tools.run_legal_benchmark.subprocess.run", side_effect=checked_subprocess), \
             mock.patch.dict(os.environ, environment, clear=True):
            return run_fake(conditions, name)

    def test_frozen_inputs_and_config_attested(self) -> None:
        metadata, questions = validate_public(ROOT)
        config = load_config()
        self.assertEqual(len(questions), 20)
        self.assertEqual(config["frozen_inputs"]["question_sha256"], EXPECTED_QUESTION_SHA256)
        self.assertEqual(config["frozen_inputs"]["corpus_source_sha256"], EXPECTED_CORPUS_SHA256)
        self.assertEqual(config["frozen_inputs"]["condition_spec_sha256"],
                         hashlib.sha256((ROOT / metadata["conditions_path"]).read_bytes()).hexdigest())
        self.assertEqual(config["attempt_count"], 1)
        self.assertEqual(config["retry_policy"], "NO_RETRIES")
        self.assertFalse(config["execution_authorized"])

    def test_frozen_config_mutations_fail_closed(self) -> None:
        from tools import run_legal_benchmark as runner
        original = runner.read_json
        for key in ("question_sha256", "condition_spec_sha256", "corpus_source_sha256", "gold_commitment_sha256"):
            with self.subTest(key=key):
                modified = copy.deepcopy(original(ROOT / CONFIG))
                modified["frozen_inputs"][key] = "0" * 64
                with mock.patch.object(runner, "read_json", side_effect=lambda path: modified if path == ROOT / CONFIG else original(path)):
                    with self.assertRaises(RunError):
                        load_config()

    def test_disclosure_shapes_and_forced_control_are_bounded(self) -> None:
        eager = initial_disclosure("EAGER")
        progressive = initial_disclosure("PROGRESSIVE")
        forced = initial_disclosure("FORCED_RETRIEVAL_CONTROL")
        self.assertIn(b"# Legal lookup", eager)
        self.assertIn(b"Corpus map", eager)
        self.assertIn(b"tools/search_sections.py", eager)
        self.assertIn(b"Capability: legal-lookup", progressive)
        self.assertNotIn(b"# Legal lookup", progressive)
        self.assertNotIn(b"Corpus map", progressive)
        self.assertEqual(progressive, forced)
        self.assertGreater(len(eager), len(progressive))
        self.assertIsNone(control_instruction("FORCED_RETRIEVAL_CONTROL", "NOT_NEEDED"))
        self.assertIsNone(control_instruction("FORCED_RETRIEVAL_CONTROL", "REUSE_OR_TARGETED"))
        self.assertIsNone(control_instruction("EAGER", "REQUIRED"))
        for lookup in ("REQUIRED", "CHECK_REQUIRED_TO_ESTABLISH_LIMITATION"):
            self.assertEqual(control_instruction("FORCED_RETRIEVAL_CONTROL", lookup), GENERIC_LOOKUP)
        for secret in (b"17-usc-708", b"answer_criteria", b"expected_sections", b"PARTIALLY_ANSWERABLE"):
            self.assertNotIn(secret, GENERIC_LOOKUP.encode())
            self.assertNotIn(secret, forced)

    def test_output_roots_and_live_authorization_fail_closed(self) -> None:
        self.assertEqual(output_root("FAKE_DRY_RUN"), DRY_ROOT)
        self.assertEqual(output_root("LIVE"), LIVE_ROOT)
        with self.assertRaises(RunError):
            output_root("FAKE_DRY_RUN", LIVE_ROOT)
        with self.assertRaises(RunError):
            output_root("LIVE", DRY_ROOT)
        with self.assertRaises(RunError):
            run_fake(["EAGER"], "test-invalid", requested_output_root=LIVE_ROOT)
        with mock.patch("sys.argv", ["runner", "--live", "--authorize-live"]), \
             mock.patch("tools.run_legal_benchmark.run_fake", side_effect=AssertionError("live ran")), \
             mock.patch("sys.stderr") as stderr:
            self.assertEqual(main(), 2)
            self.assertIn(LIVE_BLOCK, "".join(call.args[0] for call in stderr.write.call_args_list))
        with mock.patch("sys.argv", ["runner", "--dry-run", "--fake-agent", "--output-root", str(LIVE_ROOT)]), \
             mock.patch("tools.run_legal_benchmark.run_fake", wraps=run_fake) as fake, \
             mock.patch("sys.stderr"):
            self.assertEqual(main(), 1)
            fake.assert_called_once()  # run_fake rejects the root before creating anything
        with mock.patch("sys.argv", ["runner", "--live", "--authorize-live", "--output-root", str(DRY_ROOT)]), \
             mock.patch("sys.stderr"):
            self.assertEqual(main(), 1)
        self.assertEqual(list((ROOT / "results/raw").rglob("*")), self.results_before)

    def test_guarded_file_reads_deny_root_traversal_and_symlinks(self) -> None:
        root = ROOT / ".pi-cache" / ("test-" + uuid.uuid4().hex)
        root.mkdir(parents=True)
        try:
            (root / "ok.txt").write_text("ok", encoding="utf-8")
            self.assertEqual(checked_read(root, "ok.txt"), b"ok")
            (root / "escape").symlink_to(ROOT / GOLD)
            for name in (str(ROOT / GOLD), "../eval/evaluator-only/legal/v1/gold.jsonl", "escape", "results/raw"):
                with self.subTest(name=name), self.assertRaises(RunError):
                    checked_read(root, name)
        finally:
            shutil.rmtree(root)

    def test_workspace_destination_and_private_paths_fail_closed(self) -> None:
        name = "test-" + uuid.uuid4().hex
        destination = DRY_ROOT / name / "workspaces/eager" / name
        self.created.append(DRY_ROOT / name)
        workspace, manifest = build_workspace(ROOT, name, INCLUDES, destination=destination)
        self.assertEqual(workspace, destination)
        self.assertNotIn("eval/evaluator-only/legal/v1/gold.jsonl", {x["path"] for x in manifest["files"]})
        self.assertFalse((workspace / ".git").exists())
        self.assertFalse((workspace / "results").exists())
        self.assertFalse((workspace / ".pi-cache").exists())
        self.assertFalse((workspace / "eval").exists())
        self.assertFalse(any(p.is_symlink() for p in workspace.rglob("*")))
        for requested in ("eval/evaluator-only/legal/v1/gold.jsonl", "results/raw", "../AGENTS.md"):
            with self.subTest(requested=requested), self.assertRaises(WorkspaceError):
                build_workspace(ROOT, name, [requested], destination=destination)
        with self.assertRaises(WorkspaceError):
            build_workspace(ROOT, name, INCLUDES, destination=LIVE_ROOT / name)

    def test_one_condition_fake_run_and_frozen_validator(self) -> None:
        output = self.fake(["EAGER"])
        self.assertTrue(output["run_dir"].is_relative_to(DRY_ROOT))
        self.assertEqual((len(output["cases"]), len(output["turns"])), (20, 23))
        self.assertEqual(len({case["session_id"] for case in output["cases"]}), 20)
        self.assertTrue(all(t["attempt"] == 1 and t["token_usage_status"] == "UNAVAILABLE" for t in output["turns"]))
        manifest = json.loads((output["run_dir"] / "run-manifest.json").read_text())
        for field in ("model_execution_authorized", "live_model_invoked", "benchmark_scoring_performed", "canonical_result_artifact"):
            self.assertFalse(manifest[field])
        self.assertEqual(manifest["execution_kind"], "FAKE_DRY_RUN")
        self.assertFalse(json.loads((output["run_dir"] / "COMPLETED.json").read_text())["evaluation_result"])
        self.assertEqual(list((ROOT / "results/raw").rglob("*")), self.results_before)
        self.assertFalse(validate_public(ROOT)[0]["execution"]["results_exist"])

    def test_all_conditions_followups_and_gold_isolation(self) -> None:
        output = self.fake(EXPECTED_CONDITIONS)
        self.assertEqual((len(output["cases"]), len(output["turns"])), (60, 69))
        self.assertEqual(len({case["session_id"] for case in output["cases"]}), 60)
        workspaces = [json.loads(line) for line in (output["run_dir"] / "workspace-manifests.jsonl").read_text().splitlines()]
        self.assertEqual(len(workspaces), 60)
        self.assertEqual(len({row["workspace"] for row in workspaces}), 60)
        for row in workspaces:
            workspace = ROOT / row["workspace"]
            self.assertTrue(workspace.is_relative_to(output["run_dir"]))
            self.assertFalse((workspace / "eval/evaluator-only").exists())
            self.assertFalse((workspace / "results").exists())
            self.assertFalse((workspace / ".git").exists())
            self.assertFalse(any(path.is_symlink() for path in workspace.rglob("*")))
        self.assertEqual(output["disclosures"]["PROGRESSIVE"], output["disclosures"]["FORCED_RETRIEVAL_CONTROL"])
        self.assertNotEqual(output["disclosures"]["PROGRESSIVE"], output["disclosures"]["EAGER"])
        for condition in EXPECTED_CONDITIONS:
            for suffix in ("016", "017", "018"):
                rows = [row for row in output["turns"] if row["condition"] == condition and row["case_id"].endswith(suffix)]
                self.assertEqual(len(rows), 2)
                self.assertEqual(rows[0]["session_id"], rows[1]["session_id"])
                self.assertIn("prior=1", rows[1]["response_text"])
        forced = [row for row in output["turns"] if row["condition"] == "FORCED_RETRIEVAL_CONTROL"]
        self.assertIn("control_applied", next(t for t in forced if t["case_id"].endswith("019"))["event_counts"])
        self.assertNotIn("control_applied", next(t for t in forced if t["case_id"].endswith("003"))["event_counts"])
        self.assertNotIn("control_applied", next(t for t in forced if t["turn_id"].endswith("016-t2"))["event_counts"])
        for path in output["run_dir"].rglob("*"):
            if path.is_file() and path.suffix in (".json", ".jsonl"):
                text = path.read_text(encoding="utf-8")
                self.assertNotIn("answer_criteria", text)
                self.assertNotIn("PARTIALLY_ANSWERABLE", text)
        self.assertEqual(list((ROOT / "results/raw").rglob("*")), self.results_before)
        validate_public(ROOT)


if __name__ == "__main__":
    unittest.main()
