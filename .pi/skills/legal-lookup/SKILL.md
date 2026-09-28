---
name: legal-lookup
description: Use only when a user needs information from the pinned U.S. Code Title 17 corpus. Do not use for greetings, casual conversation, unrelated questions, or questions clearly outside this corpus.
---

# Legal lookup

The exact corpus version is in `corpus/manifest/title17.json`. Do not answer Title 17 corpus questions from model memory when the corpus is available.

1. If the user supplies a section or citation, run exact lookup:
   `python3 tools/search_sections.py exact "17 U.S.C. § 107" --json`
2. Otherwise locate candidates lexically:
   `python3 tools/search_sections.py search "query terms" --limit 5 --json`
3. Read each relevant `derived_file_path` XML returned by the locator before answering.
4. Answer only from supported text and cite the relevant section number(s).
5. If this pinned Title 17 release does not support the answer, state that limitation.

The pinned source XML is authoritative. Search results and the generated index are navigation aids only. Never access evaluator-only material.
