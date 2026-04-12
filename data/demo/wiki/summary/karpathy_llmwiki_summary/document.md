---
title: Summary — Karpathy's LLM Wiki Concept
type: summary
source_documents: ["demo0001-karp-athy0-llmw-iki0000000000"]
created: 2026-04-10
---

# Summary: Karpathy's LLM Wiki Concept

**Source**: Karpathy's LLM Wiki Concept (demo0001)

## Core thesis

The bottleneck in personal knowledge management is not **capture** but
**synthesis**. Tools that help you save more content without helping you
synthesize it make the problem worse, not better.

## The three-layer model

| Layer | Owner | Purpose |
|-------|-------|---------|
| Raw sources | Human | Curated, immutable source-of-truth |
| Wiki | LLM | Interlinked summaries, synthesis |
| Query interface | LLM | Talks to the wiki, not the raw files |

## Why this is novel

Most PKM tools (Obsidian, Notion, Roam) assume the human does the linking and
summarization. Karpathy's design flips that — humans curate, LLMs synthesize.

## Open problems the author acknowledges

- Drift between wiki and sources
- Handling contradictions across sources
- Right granularity for a wiki page
- When is a wiki "done" for a source?
