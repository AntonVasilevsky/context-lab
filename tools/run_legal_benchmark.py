#!/usr/bin/env python3
"""Phase 4A: fake-only legal-v1 runner. No live agent subprocess exists here."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

# Also support `python3 tools/run_legal_benchmark.py` from the repository root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_agent_workspace import build_workspace, sha256 as file_sha256
from tools.validate_legal_benchmark import (
    CONDITIONS_PATH, EXPECTED_CONDITIONS, EXPECTED_CORPUS_ID,
    EXPECTED_CORPUS_SHA256, EXPECTED_GOLD_SHA256, EXPECTED_QUESTION_SHA256,
    QUESTION_PATH, ValidationError, read_json, read_jsonl, validate_gold,
    validate_public,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG = Path("eval/runner/legal-v1-dry-run.json")
GOLD = Path("eval/evaluator-only/legal/v1/gold.jsonl")
SKILL = Path(".pi/skills/legal-lookup/SKILL.md")
RUN_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
GENERIC_LOOKUP = "Consult the pinned Title 17 corpus before answering this turn."
INCLUDES = [
    "AGENTS.md", "corpus/manifest/title17.json", "corpus/manifest/title17-sections.json",
    "corpus/source/title17/usc17.xml", "corpus/sections/title17",
    "tools/search_sections.py", SKILL.as_posix(),
]
LIVE_BLOCK = "LIVE_BLOCKED_NETWORK_ISOLATION_UNVERIFIED"
DRY_ROOT = ROOT / ".pi-cache/legal-runner-dry-runs"
LIVE_ROOT = ROOT / "results/raw/legal-v1"


class RunError(ValueError):
    pass


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def git(*arguments: str) -> str:
    return subprocess.run(["git", *arguments], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()


def output_root(execution_kind: str, requested: Path | None = None) -> Path:
    if execution_kind == "FAKE_DRY_RUN":
        root = DRY_ROOT
    elif execution_kind == "LIVE":
        root = LIVE_ROOT
    else:
        raise RunError("unknown execution kind")
    if requested is not None and requested != root:
        raise RunError(f"{execution_kind} output root must be {root}; refusing redirect")
    return root


def safe_output(path: Path, base: Path) -> None:
    if not path.is_relative_to(base) or path == base:
        raise RunError("output path escapes its run directory")
    current = ROOT
    for component in path.relative_to(ROOT).parts:
        current = current / component
        if current.is_symlink():
            raise RunError("symlink in output path")


def checked_read(workspace: Path, name: str) -> bytes:
    """Fake tool read: no absolute path, traversal, or symlink traversal."""
    posix = PurePosixPath(name)
    if not name or posix.is_absolute() or ".." in posix.parts or "\\" in name:
        raise RunError("denied path")
    current = workspace
    for part in posix.parts:
        current = current / part
        if current.is_symlink():
            raise RunError("denied symlink")
    if not current.is_file() or not current.resolve().is_relative_to(workspace.resolve()):
        raise RunError("denied missing/outside file")
    return current.read_bytes()


def skill_parts() -> tuple[str, str]:
    text = (ROOT / SKILL).read_text(encoding="utf-8")
    pieces = text.split("---", 2)
    if len(pieces) != 3:
        raise RunError("skill frontmatter missing")
    header = pieces[1]
    name = next((line[5:].strip() for line in header.splitlines() if line.startswith("name:")), None)
    description = next((line[12:].strip() for line in header.splitlines() if line.startswith("description:")), None)
    if name != "legal-lookup" or not description:
        raise RunError("legal skill metadata changed")
    return description, text


def initial_disclosure(condition: str) -> bytes:
    description, full = skill_parts()
    if condition not in EXPECTED_CONDITIONS:
        raise RunError("invalid condition")
    if condition == "EAGER":
        manifest = read_json(ROOT / "corpus/manifest/title17-sections.json")
        # Headings and IDs only; never pre-load section text.
        compact = "\n".join(f"{s['citation']} — {s['heading']}" for s in manifest["sections"])
        text = (
            "Legal lookup workflow (complete):\n" + full + "\n"
            "Corpus map (section citations/headings; navigation only):\n" + compact + "\n"
            "Candidate locator: tools/search_sections.py; source: corpus/source/title17/usc17.xml.\n"
        )
    else:
        text = f"Capability: legal-lookup\nDescription: {description}\n"
    return text.encode("utf-8")


def control_instruction(condition: str, lookup: str | None) -> str | None:
    if condition == "FORCED_RETRIEVAL_CONTROL" and lookup in {
        "REQUIRED", "CHECK_REQUIRED_TO_ESTABLISH_LIMITATION"
    }:
        return GENERIC_LOOKUP
    return None


def load_config() -> dict:
    config = read_json(ROOT / CONFIG)
    benchmark = read_json(ROOT / "eval/benchmark/legal/v1.json")
    if config.get("schema_version") != 1 or config.get("benchmark_id") != "legal-v1":
        raise RunError("invalid runner configuration")
    frozen = {
        "question_sha256": EXPECTED_QUESTION_SHA256,
        "condition_spec_sha256": file_sha256(ROOT / CONDITIONS_PATH),
        "corpus_id": EXPECTED_CORPUS_ID,
        "corpus_source_sha256": EXPECTED_CORPUS_SHA256,
        "gold_commitment_sha256": EXPECTED_GOLD_SHA256,
    }
    if config.get("frozen_inputs") != frozen:
        raise RunError("frozen run inputs mismatch")
    if benchmark["gold_commitment"]["sha256"] != EXPECTED_GOLD_SHA256:
        raise RunError("frozen manifest changed")
    if config.get("experimental_model") != "EXPERIMENT_MODEL_UNAPPROVED" or config.get("experimental_provider") != "UNAPPROVED":
        raise RunError("experimental model/provider approval has not occurred")
    if config.get("execution_authorized") is not False or config.get("execution_kind") != "FAKE_DRY_RUN":
        raise RunError("Phase 4A execution must be fake-only and unauthorized")
    if any(config.get(key) is not False for key in (
        "model_execution_authorized", "live_model_invoked", "benchmark_scoring_performed",
        "canonical_result_artifact"
    )):
        raise RunError("fake artifacts cannot claim live or scored status")
    if config.get("attempt_count") != 1 or config.get("retry_policy") != "NO_RETRIES":
        raise RunError("only one attempt and no retries are allowed")
    if config.get("network_policy") != "LIVE_BLOCKED_UNVERIFIED" or config.get("workspace_policy") != "STAGED_ALLOWLIST_PER_CASE":
        raise RunError("unsafe policy configuration")
    if config.get("condition_order") != EXPECTED_CONDITIONS or config.get("case_selection") != "ALL_FROZEN_ORDER":
        raise RunError("unexpected execution order")
    if config.get("temperature") is not None:
        raise RunError("temperature has not been approved")
    return config


def attestation(config: dict, *, live: bool) -> dict:
    metadata, questions = validate_public(ROOT)
    if file_sha256(ROOT / QUESTION_PATH) != EXPECTED_QUESTION_SHA256:
        raise RunError("question checksum mismatch")
    if file_sha256(ROOT / CONDITIONS_PATH) != config["frozen_inputs"]["condition_spec_sha256"]:
        raise RunError("condition checksum mismatch")
    if file_sha256(ROOT / metadata["corpus"]["source_xml_path"]) != EXPECTED_CORPUS_SHA256:
        raise RunError("corpus checksum mismatch")
    # Explicit private-side check; gold never goes into the workspace or transcript.
    if not (ROOT / GOLD).is_file():
        raise RunError("private evaluator gold missing")
    validate_gold(ROOT, metadata, questions, GOLD)
    head = git("rev-parse", "HEAD")
    upstream = git("rev-parse", "origin/main")
    clean = not git("status", "--porcelain", "--untracked-files=normal")
    if live and (not clean or head != upstream or head != config.get("runner_git_commit")):
        raise RunError("LIVE_BLOCKED_REPRODUCIBILITY_ATTESTATION")
    return {
        "head": head, "origin_main": upstream, "tracked_tree_clean": clean,
        "runner_git_commit": head, "frozen_question_sha256": EXPECTED_QUESTION_SHA256,
        "condition_spec_sha256": config["frozen_inputs"]["condition_spec_sha256"],
        "corpus_source_sha256": EXPECTED_CORPUS_SHA256,
        "gold_commitment_sha256": EXPECTED_GOLD_SHA256,
        "gold_present_evaluator_side": True, "gold_present_agent_side": False,
        "network_isolation_verified": False, "filesystem_isolation_verified": False,
    }


class FakeAgent:
    """No subprocess, network, model, or real retrieval. One object per case."""

    def __init__(self, session_id: str, workspace: Path):
        self.session_id = session_id
        self.workspace = workspace
        self.history: list[tuple[str, str]] = []

    def turn(self, prompt: str, control: str | None, ordinal: int) -> tuple[str, list[dict]]:
        events: list[dict] = []
        if control:
            events.append({"type": "control_applied", "instruction": control})
            data = checked_read(self.workspace, SKILL.as_posix())
            events.extend([
                {"type": "skill_selected", "name": "legal-lookup", "fake": True},
                {"type": "legal_skill_loaded", "path": SKILL.as_posix(), "bytes_read": len(data), "fake": True},
            ])
        response = f"FAKE_AGENT_RESPONSE session={self.session_id} turn={ordinal} prior={len(self.history)}"
        self.history.append((prompt, response))
        return response, events


def event_counts(events: list[dict]) -> dict:
    counts = Counter(event["type"] for event in events)
    return dict(sorted(counts.items()))


def run_fake(conditions: list[str], run_id: str, *, requested_output_root: Path | None = None) -> dict:
    if not RUN_ID.fullmatch(run_id):
        raise RunError("invalid run ID")
    if not conditions or len(conditions) != len(set(conditions)) or any(c not in EXPECTED_CONDITIONS for c in conditions):
        raise RunError("invalid or repeated condition")
    root = output_root("FAKE_DRY_RUN", requested_output_root)
    config = load_config()
    attest = attestation(config, live=False)
    questions = read_jsonl(ROOT / QUESTION_PATH)
    gold = read_jsonl(ROOT / GOLD, require_canonical=True)
    expected_lookup = {
        turn["turn_id"]: turn["lookup_expectation"]
        for case in gold for turn in case["turn_expectations"]
    }
    base = root / run_id
    safe_output(base, root)
    if base.exists():
        raise RunError("run ID already exists; no result-driven reruns or overwrites")
    base.mkdir(parents=True)
    turns: list[dict] = []
    cases: list[dict] = []
    events_file = base / "session-events.jsonl"
    turns_file = base / "per-turn.jsonl"
    cases_file = base / "per-case.jsonl"
    workspaces: list[dict] = []
    disclosure_hashes: dict[str, str] = {}
    manifest = {
        **config, "runner_git_commit": attest["head"], "run_id": run_id,
        "mode": "DRY_RUN_FAKE_ONLY", "condition_order": conditions,
        "case_order": [case["question_id"] for case in questions],
        "execution_kind": "FAKE_DRY_RUN", "model_execution_authorized": False,
        "live_model_invoked": False, "benchmark_scoring_performed": False,
        "canonical_result_artifact": False, "fake_output_not_benchmark_result": True,
    }
    (base / "run-manifest.json").write_bytes(json_bytes(manifest))
    (base / "environment-attestation.json").write_bytes(json_bytes(attest))
    with turns_file.open("wb") as turn_stream, events_file.open("wb") as event_stream, cases_file.open("wb") as case_stream:
        for condition in conditions:
            disclosure = initial_disclosure(condition)
            digest = hashlib.sha256(disclosure).hexdigest()
            disclosure_hashes[condition] = digest
            for case in questions:
                case_id = case["question_id"]
                workspace_path = base / "workspaces" / condition.lower().replace("_", "-") / case_id
                workspace, workspace_manifest = build_workspace(
                    ROOT, case_id, INCLUDES, destination=workspace_path
                )
                # No private, results, repo metadata, or unlisted files in the agent workspace.
                paths = {file["path"] for file in workspace_manifest["files"]}
                if any(path.startswith(("eval/", "results/", ".git/", ".pi-cache/")) for path in paths):
                    raise RunError("workspace contains forbidden files")
                workspaces.append({"condition": condition, "case_id": case_id,
                                   "manifest_sha256": file_sha256(workspace / ".workspace-manifest.json"),
                                   "workspace": workspace.relative_to(ROOT).as_posix()})
                session_id = f"fake-{condition.lower()}-{case_id}"
                agent = FakeAgent(session_id, workspace)
                case_turns = []
                for index, turn in enumerate(case["turns"], start=1):
                    turn_id = turn["turn_id"]
                    control = control_instruction(condition, expected_lookup[turn_id])
                    started = utc_now()
                    response, events = agent.turn(turn["prompt"], control, index)
                    completed = utc_now()
                    # Fixed fake measurements are not claims about model speed or tokens.
                    metrics = {
                        "schema_version": 1, "case_id": case_id, "turn_id": turn_id,
                        "condition": condition, "attempt": 1, "session_id": session_id,
                        "started_at": started, "completed_at": completed, "wall_clock_ms": 0,
                        "provider": None, "model": None, "reasoning": None,
                        "input_tokens": None, "output_tokens": None, "total_tokens": None,
                        "token_usage_status": "UNAVAILABLE", "fake_fixed_tokens": {"input": 11, "output": 7},
                        "initial_disclosure_bytes": len(disclosure), "initial_disclosure_sha256": digest,
                        "event_counts": event_counts(events), "files_opened": [event["path"] for event in events if event["type"] == "legal_skill_loaded"],
                        "section_ids_opened": [], "candidate_sections_returned": 0,
                        "section_files_opened": 0, "response_text": response,
                        "error_classification": None, "fake": True,
                    }
                    turn_stream.write(json_bytes(metrics))
                    case_turns.append(metrics)
                    for event in events:
                        event_stream.write(json_bytes({"case_id": case_id, "turn_id": turn_id,
                                                       "session_id": session_id, "condition": condition, **event}))
                case_metrics = {"schema_version": 1, "case_id": case_id, "condition": condition,
                                "session_id": session_id, "attempt": 1, "turn_count": len(case_turns),
                                "wall_clock_ms": sum(t["wall_clock_ms"] for t in case_turns),
                                "event_count": sum(sum(t["event_counts"].values()) for t in case_turns),
                                "fake": True}
                case_stream.write(json_bytes(case_metrics))
                cases.append(case_metrics)
                turns.extend(case_turns)
    (base / "workspace-manifests.jsonl").write_bytes(b"".join(json_bytes(item) for item in workspaces))
    (base / "stdio.json").write_bytes(json_bytes({"stdout": "", "stderr": "", "agent_subprocess_started": False}))
    (base / "initial-disclosures.json").write_bytes(json_bytes({c: {
        "utf8": initial_disclosure(c).decode("utf-8"),
        "sha256": disclosure_hashes[c], "bytes": len(initial_disclosure(c))
    } for c in conditions}))
    (base / "COMPLETED.json").write_bytes(json_bytes({"execution_kind": "FAKE_DRY_RUN", "cases": len(cases),
                                                   "turns": len(turns), "evaluation_result": False,
                                                   "live_model_invoked": False, "scored": False}))
    return {"run_dir": base, "cases": cases, "turns": turns, "disclosures": disclosure_hashes}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--live", action="store_true")
    parser.add_argument("--fake-agent", action="store_true")
    parser.add_argument("--condition", choices=["ALL", *EXPECTED_CONDITIONS], default="ALL")
    parser.add_argument("--run-id", default="phase4a-fake")
    parser.add_argument("--authorize-live", action="store_true")
    parser.add_argument("--output-root", type=Path, help="exact mode-specific absolute output root; no redirects")
    args = parser.parse_args()
    try:
        # No live adapter exists. This check precedes any model, tool, or agent invocation.
        if args.live:
            output_root("LIVE", args.output_root)
            # No live adapter exists, even when both gates are requested. Do not create results.
            print(LIVE_BLOCK, file=sys.stderr)
            return 2
        if not args.fake_agent or args.authorize_live:
            raise RunError("dry-run requires --fake-agent and forbids live authorization")
        conditions = EXPECTED_CONDITIONS if args.condition == "ALL" else [args.condition]
        output = run_fake(conditions, args.run_id, requested_output_root=args.output_root)
        print(f"fake-only dry-run: {len(output['cases'])} cases / {len(output['turns'])} turns; {output['run_dir']}")
        return 0
    except (OSError, subprocess.CalledProcessError, ValidationError, RunError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
