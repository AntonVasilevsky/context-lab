---
name: legal-lookup
description: Use for questions that require information from the pinned U.S. Code Title 17 corpus. Do not use for unrelated conversation or questions outside that corpus.
---

# Legal lookup

The exact corpus version is recorded in `corpus/manifest/title17.json`. It covers only that pinned Title 17 release. Do not produce corpus-specific answers from model memory.

Future retrieval must identify candidate sections, and you must read the retrieved section text before answering. Cite relevant section numbers. The pinned source XML is authoritative; derived sections and future search results only aid navigation.

Never read, search, index, quote, or expose evaluator-only files. No legal lookup command is implemented yet.
