# Karpathy's LLM Wiki Concept

In late 2025, Andrej Karpathy shared a gist describing his ideal workflow for
using large language models to maintain a personal knowledge base. He proposed
three layers:

1. **Raw sources** — an immutable, curated document collection that you trust.
2. **The wiki** — LLM-generated, interlinked summaries written on top of the
   raw layer. This is where synthesis happens.
3. **The query interface** — you talk to the wiki, not the raw files. Token
   budgets are drastically lower because the wiki has already done the work of
   distillation.

## Why this matters

Traditional note-taking tools (Obsidian, Notion, Roam) require the human to do
all the linking, summarization, and synthesis. Karpathy's proposal flips that:
the LLM owns the synthesis layer. Humans curate sources and ask questions; the
LLM maintains the map between them.

Key claim: **the bottleneck in personal knowledge management is not capture,
it's synthesis**. Tools that only help you capture more (web clippers, read-it-
later apps) make the problem worse. Tools that automate synthesis are rare.

## Open problems

- How do you prevent the wiki from drifting away from the sources?
- How do you handle contradictions between sources?
- What's the right granularity for a wiki page?
- How do you know when the wiki is "done" for a given source?

These are the problems PageFly's Compiler Agent tries to answer.
