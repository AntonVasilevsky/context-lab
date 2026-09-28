# Tools

## Deterministic Title 17 retrieval

`search_sections.py` provides the Phase 3A structured/lexical baseline. It is a candidate locator, not answer generation and not semantic RAG. Returned candidates omit full legal text; read the returned derived XML file separately.

```sh
python3 tools/search_sections.py build --json
python3 tools/search_sections.py exact "17 U.S.C. § 107" --json
python3 tools/search_sections.py search "limitations on exclusive rights fair use" --limit 5 --json
```

Exact lookup accepts a bare section, `§` form, or Title 17 U.S.C. citation and performs no fuzzy interpretation. Lexical lookup uses the Python standard library's SQLite FTS5 support. Its rebuildable index is stored at `.pi-cache/legal-search/title17-fts5-v1.sqlite3` and is never authoritative.

Index input is restricted to `corpus/manifest/title17-sections.json`, its listed files under `corpus/sections/title17/`, and pinned source identity metadata. Before use, source and section hashes are verified. Missing, stale, or corrupt regular index files are rebuilt atomically; unsafe paths and symlinks fail closed.

### Search normalization and ranking

Search text is obtained by concatenating all XML text nodes in document order, then applying Unicode NFC, Unicode case-folding, and whitespace collapse. No subsection content is removed and source XML is never modified. Query terms are Unicode letter/number runs; FTS candidate matching uses their deterministic OR union.

Candidates receive an integer score:

- exact section number: 100,000;
- exact heading: 20,000;
- query phrase in heading: 10,000;
- query phrase in complete searchable text: 2,000;
- per query term: section-number frequency × 1,000, citation × 500, heading × 200, complete text × 10;
- each unique query term present: 100.

Results sort by descending score, then section-manifest ordinal. No synonyms, query rewriting, model calls, or semantic expansion are used. Build timing and index size are emitted as build metrics; query latency is measured separately. XML byte size and normalized searchable-text character count are measurements, not model token estimates.

## Frozen legal benchmark validation

`validate_legal_benchmark.py` validates the immutable 20-case `legal-v1` artifact, pinned-corpus identity, approved question checksum, condition specification, gold commitment, and unexecuted status without network or model calls:

```sh
python3 tools/validate_legal_benchmark.py
```

The evaluator can additionally verify ignored canonical gold against the frozen SHA-256 commitment and generate an ignored local review packet:

```sh
python3 tools/validate_legal_benchmark.py \
  --gold eval/evaluator-only/legal/v1/gold.jsonl \
  --review-output .pi-cache/legal-benchmark-v1-review.md
```

Gold must remain under `eval/evaluator-only/`; review output is restricted to `.pi-cache/`. Neither belongs in an agent workspace. Validation does not authorize or execute the benchmark.

## Other Phase 2 tools

- `prepare_title17.py` deterministically extracts and validates the pinned official XML.
- `build_agent_workspace.py` copies explicit allowlisted files into an isolated staged workspace.

Future phases may add semantic retrieval, hybrid retrieval, Graphify candidate routing, and an instrumented evaluation runner. None is implemented here. All tools must exclude `eval/evaluator-only/` and treat original corpus or code files as authoritative.
