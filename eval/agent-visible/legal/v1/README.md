# Legal benchmark v1 — frozen agent-visible questions

**Status: `FROZEN`. Live execution is not authorized.**

`questions.jsonl` is the owner-approved 20-case legal pilot. Its immutable SHA-256 is `22337618074909dd9fec0e55877d838ddb68070aee1d937f2b602c057821087a`. Each UTF-8 JSONL object has only:

- `question_id`: stable case ID;
- `turns`: one prompt, or two prompts for a conversational case;
- `turn_id`: stable turn ID; and
- `prompt`: the exact frozen user text.

The `legal-v1-draft-*` case and turn IDs are intentionally retained as immutable historical identifiers. No expected routing, expected sections, answer criteria, or gold answers belong in this directory. A future runner must pass only the active prompt and condition-authorized files to the agent, not the JSON wrapper or benchmark metadata.

The benchmark includes 23 turns because three cases contain a follow-up. Follow-ups are end-to-end conversational cases: for each condition, the t1 user prompt is followed by that condition’s actual agent response and then the t2 user prompt in the same session. Prior assistant context before t2 may therefore differ across conditions. Record both per-turn and case/conversation-level measurements; do not interpret t2 as an identical-input paired A/B comparison. A future experiment requiring identical prior assistant context must use a separate benchmark/version with frozen assistant messages; `legal-v1` contains no frozen assistant replies. Separate cases must use fresh sessions. Source answers must treat the pinned XML as authoritative.

The tracked benchmark manifest records the frozen condition specification and SHA-256 commitment to canonical evaluator gold. Gold remains ignored, local, and outside every staged agent workspace under the commit–reveal protocol. Freezing does not authorize or execute the benchmark. See `EXPERIMENT.md` for the post-freeze change rule and evaluator-isolation requirements.
