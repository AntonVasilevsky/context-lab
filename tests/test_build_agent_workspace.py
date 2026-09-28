from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.build_agent_workspace import MANIFEST_NAME, WorkspaceError, build_workspace


class AgentWorkspaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        (self.root / "eval/agent-visible/legal").mkdir(parents=True)
        (self.root / "eval/evaluator-only/legal").mkdir(parents=True)
        (self.root / ".git").mkdir()
        (self.root / "AGENTS.md").write_text("agent guidance\n", encoding="utf-8")
        (self.root / "eval/agent-visible/legal/case.txt").write_text("visible\n", encoding="utf-8")
        (self.root / "eval/evaluator-only/legal/answers.txt").write_text("secret\n", encoding="utf-8")
        (self.root / ".git/config").write_text("git metadata\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def build(self, includes: list[str] | None = None):
        return build_workspace(
            self.root,
            "legal-test",
            includes or ["AGENTS.md", "eval/agent-visible/legal"],
        )

    def test_agent_visible_content_may_be_staged(self) -> None:
        workspace, _ = self.build()
        self.assertEqual((workspace / "AGENTS.md").read_text(), "agent guidance\n")
        self.assertTrue((workspace / "eval/agent-visible/legal/case.txt").is_file())

    def test_evaluator_only_content_cannot_be_staged(self) -> None:
        with self.assertRaises(WorkspaceError):
            self.build(["eval/evaluator-only/legal/answers.txt"])

    def test_parent_traversal_is_rejected(self) -> None:
        with self.assertRaises(WorkspaceError):
            self.build(["../outside.txt"])

    def test_absolute_external_path_is_rejected(self) -> None:
        with self.assertRaises(WorkspaceError):
            self.build(["/etc/passwd"])

    def test_unknown_path_fails_closed(self) -> None:
        with self.assertRaises(WorkspaceError):
            self.build(["eval/agent-visible/legal/missing.txt"])

    def test_symlink_escape_is_rejected(self) -> None:
        external = Path(self.temporary.name).parent / "context-lab-external-test.txt"
        external.write_text("outside\n", encoding="utf-8")
        try:
            (self.root / "eval/agent-visible/legal/escape").symlink_to(external)
            with self.assertRaises(WorkspaceError):
                self.build(["eval/agent-visible/legal"])
        finally:
            external.unlink(missing_ok=True)

    def test_workspace_has_no_evaluator_tree_or_git_metadata(self) -> None:
        workspace, _ = self.build()
        self.assertFalse((workspace / "eval/evaluator-only").exists())
        self.assertFalse((workspace / ".git").exists())
        self.assertFalse(any(path.is_symlink() for path in workspace.rglob("*")))

    def test_manifest_lists_only_approved_paths(self) -> None:
        workspace, manifest = self.build()
        recorded = {entry["path"] for entry in manifest["files"]}
        self.assertEqual(recorded, {"AGENTS.md", "eval/agent-visible/legal/case.txt"})
        on_disk = json.loads((workspace / MANIFEST_NAME).read_text(encoding="utf-8"))
        self.assertEqual(on_disk, manifest)
        self.assertFalse(any(path.startswith("eval/evaluator-only") for path in recorded))

    def test_rebuild_replaces_workspace_deterministically(self) -> None:
        workspace, first = self.build()
        first_manifest = (workspace / MANIFEST_NAME).read_bytes()
        (workspace / "unapproved.txt").write_text("remove me", encoding="utf-8")
        rebuilt, second = self.build()
        self.assertFalse((rebuilt / "unapproved.txt").exists())
        self.assertEqual(first, second)
        self.assertEqual(first_manifest, (rebuilt / MANIFEST_NAME).read_bytes())


if __name__ == "__main__":
    unittest.main()
