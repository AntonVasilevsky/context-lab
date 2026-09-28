# Tools

Future phases may add:

- deterministic section search for the pinned legal corpus;
- a constrained Graphify wrapper for candidate-source routing; and
- an evaluation runner with cost, timing, routing, retrieval, and answer-quality instrumentation.

None of these tools is implemented in Phase 1. Any future tool must be restricted to the repository root, must exclude `eval/evaluator-only/` from agent access and indexing, and must treat original corpus or code files as authoritative.
