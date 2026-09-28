# Tools

Phase 2 provides:

- `prepare_title17.py`, a deterministic extractor and validator for the pinned official XML; and
- `build_agent_workspace.py`, an explicit-allowlist workspace builder that physically excludes evaluator-only and other forbidden material.

Future phases may add deterministic section search, a constrained Graphify wrapper for candidate-source routing, and an instrumented evaluation runner. None is implemented yet.

Any future tool must be restricted to the repository root, exclude `eval/evaluator-only/` from agent access and indexing, and treat original corpus or code files as authoritative.
