# Legal benchmark v1 draft — agent-visible questions

**Status: `DRAFT_OWNER_REVIEW`. This set is not frozen and must not be executed.**

`questions.jsonl` contains the proposed 20-case legal pilot. Each UTF-8 JSONL object has only:

- `question_id`: stable draft case ID;
- `turns`: one prompt, or two prompts for a conversational case;
- `turn_id`: stable turn ID; and
- `prompt`: the exact proposed user text.

No expected routing, expected sections, answer criteria, or gold answers belong in this directory. A future runner must pass only the active prompt and condition-authorized files to the agent, not the JSON wrapper or benchmark metadata.

The draft includes 23 turns because three cases contain a follow-up. Follow-up turns must share their case session; separate cases must use fresh sessions. Source answers must treat the pinned XML as authoritative.

The tracked benchmark metadata records a SHA-256 commitment to canonical evaluator gold. The gold and owner review packet are ignored local files and must remain outside every staged agent workspace. Owner approval and a separate freeze step are required before any live model run.
