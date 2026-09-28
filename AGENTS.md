# Agent guidance

This repository is an experimental context-selection and retrieval sandbox. See [EXPERIMENT.md](EXPERIMENT.md) for the full protocol.

- Source corpora are immutable once frozen, and original source files are authoritative.
- Keep agent-visible and evaluator-only data technically separate. Evaluator-only data must never enter an agent prompt or tool result.
- No experiment or experimental tool may read or index anything outside this repository root.
- Do not run models or APIs unless the current experiment phase explicitly authorizes it.
- Do not tune from observed results inside a frozen experiment version.
- Treat derived indexes, search results, and graphs only as candidate-source mechanisms, never as truth.
- Load future skills only when relevant. Simple irrelevant conversation must not trigger corpus or code lookup.
- Deterministic search remains a valid baseline.
