# Purpose

`context-lab` investigates two independent hypotheses:

1. whether progressive disclosure can reduce unnecessary context loading for a large textual knowledge source while preserving reliable retrieval; and
2. whether Graphify-assisted candidate routing adds useful navigation value for questions about relationships across a codebase.

The experiments concern context selection, retrieval, and code navigation—not legal advice. Source files remain authoritative in every condition.

# Hypothesis 1 — Progressive disclosure

The progressive-disclosure experiment will compare three future conditions.

## A. EAGER

- Detailed legal lookup instructions and a corpus map are available from the start.
- Actual corpus sections are still retrieved only when needed.

## B. PROGRESSIVE

- Only a compact skill description is initially visible.
- Full legal lookup instructions and source sections are opened only when the agent decides they are necessary.

## C. FORCED-RETRIEVAL CONTROL

- For questions known by the evaluator to require the legal corpus, retrieval is explicitly required.
- This is a diagnostic condition, not necessarily a proposed production design.

Comparing the progressive and forced-retrieval conditions helps distinguish routing or skill-selection failure from retrieval failure after invocation. Follow-ups should use conversation context plus targeted retrieval rather than loading the complete corpus. Questions beyond the pinned corpus should receive an appropriate limitation instead of an invented answer.

# Hypothesis 2 — Graphify

Graphify will be evaluated in two separate experiments.

## A. AUTONOMOUS ROUTING

The agent decides whether ordinary deterministic search or Graphify is useful for the question.

## B. FORCED A/B

- Identical frozen questions are used in both conditions.
- One condition requires deterministic search.
- The other requires Graphify candidate routing.
- Both conditions must inspect original source files before answering.

Autonomous tool selection and Graphify retrieval quality are different questions and must not be conflated. Graphify output is a navigation aid, never an authoritative source.

# Source corpora

## Legal corpus

- The official U.S. Code Title 17 XML release current through Public Law 119-111 (September 18, 2026) is pinned in `corpus/manifest/title17.json` with its exact URL and checksums.
- The original ZIP and extracted XML remain immutable. The XML is authoritative.
- Deterministically derived per-section XML files are navigation and source fragments, not replacements for the pinned XML. Their scope and checksums are recorded in `corpus/manifest/title17-sections.json`.

## Future code corpus

- One pinned commit of the public `spring-projects/spring-petclinic` repository.
- Its exact commit SHA will be recorded later.
- The code snapshot will remain immutable for an experiment version.

No code commit is pinned yet.

# Legal retrieval baselines

Phase 3A provides structured exact-section lookup and deterministic lexical search over the derived Title 17 section files. The generated SQLite FTS5 index is ignored, reproducible derived state and a candidate-source mechanism only; the pinned source XML remains authoritative. This baseline is not semantic RAG and performs no semantic expansion or model calls.

A later independent legal-retrieval experiment may compare:

A. structured/lexical retrieval;
B. semantic RAG; and
C. hybrid lexical + semantic retrieval.

Those conditions must use the same frozen corpus and question set. Conditions B and C are not implemented in Phase 3A.

# Agent-visible vs evaluator-only boundary

**Agent-visible material** consists only of:

- questions given to the agent;
- the source corpus and tools allowed by the active condition; and
- skill descriptions and instructions exposed by that condition.

**Evaluator-only material** includes:

- expected source sections or files;
- correctness rubrics;
- expected routing decisions;
- human review notes; and
- aggregate comparison logic.

Evaluator-only content must not be reachable by the agent process and must never be indexed by retrieval or Graphify tooling. `tools/build_agent_workspace.py` now stages real files from a legal-experiment allowlist into ignored local state and physically omits evaluator-only data, repository metadata, results, secrets, symlinks, and paths outside the repository. Future agents must run against a condition-specific staged workspace rather than the repository root. For every future live run, evaluator gold must be physically absent from that workspace, unreachable through the network or GitHub, and the agent must have no access to the repository root outside the staged workspace. A future runner must preserve and enforce this boundary.

# Evaluation dimensions

Every future case will capture at least:

## Identity and configuration

- `question_id`
- experiment/version
- condition/mode
- model
- reasoning
- session identifier

## Routing

- lookup/tool expected?
- lookup/tool selected?
- unnecessary lookup?
- missed lookup?

## Retrieval

- candidate source count
- source files/sections opened
- expected source recall
- irrelevant source count

## Model cost

- prompt tokens
- completion tokens
- total tokens

## Timing

- search/tool latency
- model latency
- total wall-clock latency

## Answer quality

- correctness
- source-groundedness
- unsupported claims
- appropriate limitation/refusal when outside the corpus

## Additional graph metrics

- graph build time
- graph build token/API cost, if any
- graph query latency
- graph candidate count

Index-build cost and time must be recorded separately from per-query cost and time. Routing quality and retrieval quality must also be evaluated separately.

# Evaluation question classes

The owner-approved legal benchmark is frozen as `legal-v1` under `eval/agent-visible/legal/v1/`: four no-lookup, four exact-citation, four single-section natural-language, three multi-section, three conversational follow-up, and two out-of-corpus or insufficient-evidence cases. Evaluator expectations remain in ignored local gold; only its SHA-256 commitment is tracked. `FROZEN` does not mean executed: live runs are not authorized and no benchmark results exist.

The planned code set will cover:

- simple known/local lookup
- cross-layer call/data flow
- multiple implementations/adapters
- persistence relationship
- a question where lexical search should be sufficient
- a question where graph relationships might reduce search space

The legal-v1 questions and evaluation contract are frozen. The planned code set is not frozen.

# Interpretation discipline

The first pilot will be descriptive rather than a statistically powered benchmark.

For progressive disclosure, a result is **promising** only if:

- context/token use decreases;
- routing remains reliable; and
- source retrieval and answer quality do not visibly degrade on the frozen pilot set.

For Graphify, a result is **promising** only if it provides a measurable navigation benefit, such as:

- fewer candidate or opened files;
- lower downstream context/token usage;
- better expected-source recall; or
- improved answer quality on relationship-heavy questions.

Interpretation must separately account for index construction cost, query latency, and complexity/maintenance cost. Graphify does not need to beat lexical search on simple or local questions. A valid result may be a conditional policy such as:

- simple/local → deterministic search;
- unfamiliar cross-module relationship → Graphify.

# Freeze/version rules

Before live evaluation:

- corpus version is pinned;
- code commit is pinned;
- questions are frozen;
- expected sources are frozen;
- prompts and skill versions are frozen;
- model and reasoning setting are frozen; and
- runner commit is recorded.

All comparison modes must use the same model, reasoning setting, frozen question set, and corpus version, with fresh sessions where required.

`legal-v1` must not be edited in place after freeze. Any semantic change to its questions, gold, conditions, corpus, or evaluation contract requires a new benchmark version such as `legal-v2`. Runner implementation fixes may be versioned separately, but must not silently mutate frozen benchmark inputs.

After the first live output of an experiment version:

- no tuning is allowed within that version; and
- changes to prompts, tools, corpora, questions, expected answers/sources, or evaluation logic require a new explicitly identified experiment version.
