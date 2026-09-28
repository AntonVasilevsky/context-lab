# context-lab

`context-lab` is a public experimental sandbox for testing context selection and source navigation. It is independent of any production or private project and contains no private-project material.

The project has two tracks:

1. **Progressive context disclosure:** test whether an agent avoids an irrelevant large textual corpus while reliably finding and reading targeted source fragments when needed.
2. **Graph-assisted code navigation:** compare deterministic code search with Graphify-assisted candidate routing for relationship-heavy questions, while treating original source files as authoritative.

The planned legal corpus is for retrieval research only. Nothing in this repository is legal advice.

**Status: Phase 3A — deterministic Title 17 retrieval baseline.** The official Title 17 XML release current through Public Law 119-111 (September 18, 2026) is pinned with provenance and checksums. The unchanged XML is authoritative; deterministically derived per-section XML files are source fragments for navigation. A staged-workspace builder physically excludes evaluator-only material from future agent workspaces.

A local tool now provides exact citation lookup and deterministic SQLite FTS5 lexical candidate search. Its generated index is ignored derived state and is not authoritative. This baseline is not semantic RAG. A future independent experiment may compare structured/lexical retrieval, semantic RAG, and hybrid lexical + semantic retrieval using the same frozen corpus and question set.

No evaluation questions or live model results exist yet. PetClinic and Graphify are not installed. See [EXPERIMENT.md](EXPERIMENT.md) for the protocol.
