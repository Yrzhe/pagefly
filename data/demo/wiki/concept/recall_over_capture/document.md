---
title: Recall Over Capture
type: concept
sources: ["demo0003-spac-edre-peti-tion0000000000"]
created: 2026-04-10
updated: 2026-04-10
---

# Recall Over Capture

A knowledge base you cannot recall from is just storage. The value of a PKM
system is measured in **retrieved insights per week**, not in stored documents.

## The forgetting curve

Hermann Ebbinghaus showed in 1885 that memory decays exponentially without
review — recall drops to roughly 40% within a day. Every PKM tool inherits
this problem: no matter how neatly your notes are organized, if you never
revisit them, they might as well not exist.

## Desirable difficulty

The effort of reconstructing a memory is what strengthens it. This has two
implications for PKM design:

1. **Active review beats passive browsing**. A weekly review that forces you
   to explain what you learned is worth more than 100 hours of scrolling.
2. **Search is better than categorization**. Searching requires recall of a
   keyword; browsing a folder tree does not.

## Implication for wiki design

A wiki compiled by an LLM only has value if it's **queried** often. PageFly
therefore pairs its compilation pipeline with a query agent, and schedules
periodic reviews that force the wiki to be re-read and re-synthesized.
