---
title: Atomic Ideas
type: concept
sources: ["demo0002-zett-elka-sten-intro00000000"]
created: 2026-04-10
updated: 2026-04-10
---

# Atomic Ideas

An **atomic idea** is a single, self-contained claim that can be named, linked,
and cited independently. The term comes from the Zettelkasten tradition, where
the rule "one idea per note" is the foundation that makes the whole system
work.

## Why atomicity matters

1. **Naming**: if a note contains two ideas, you cannot give it a precise name.
2. **Linking**: a link should connect *this specific idea* to *that specific
   idea*, not "topic A is vaguely related to topic B."
3. **Recall**: atomic ideas are easier to retrieve because each one has a
   unique address in your knowledge base.

## Counter-examples

- "Notes on Chapter 3 of Book X" — not atomic. Contains dozens of ideas.
- "Interesting things about LLMs" — not atomic. The scope is too broad to be
  useful as a link target.
- "The spacing effect explains why review at increasing intervals works" —
  atomic. Named, precise, can be linked from anywhere that discusses memory.

## Relationship to compilation

When an LLM compiles a wiki from raw sources, the output should be atomic
concept pages, not chapter summaries. This is why PageFly's Compiler Agent
produces many small concept pages rather than one long "notes on source X"
document.
