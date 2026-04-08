# PageFly Wiki Schema

> This document defines the structure and conventions for the PageFly knowledge system.
> All agents read this as context. It co-evolves with the system over time.

## Data Layers

```
data/
├── inbox/         ← Drop files for auto-ingest
├── raw/           ← Freshly ingested (pre-classification)
├── knowledge/     ← Classified documents (source of truth)
├── wiki/          ← Compiled articles (LLM-maintained)
├── workspace/     ← Agent scratch area (temporary)
├── log.md         ← Current week's activity log
└── log_archive/   ← Archived weekly logs
```

- **knowledge/** is immutable to agents — only the governance pipeline writes here
- **wiki/** is the agent's domain — Compiler creates and updates articles here
- **workspace/** is temporary — auto-cleaned after 7 days, not tracked in DB

## Knowledge Documents

### Structure
```
knowledge/{category}/{subcategory?}/{title}_{id[:8]}/
├── document.md      ← Content (markdown)
├── metadata.json    ← Structured metadata
└── images/          ← Extracted images (optional)
```

### Categories
| ID | Name | Subcategories |
|----|------|---------------|
| research | Research | semiconductor, ai, quant, macro |
| tech | Technology | frontend, backend, ai-engineering, devops, tools |
| finance | Finance | a-shares, us-stocks, crypto, investment-strategy |
| people | People | — |
| projects | Projects | — |
| ideas | Ideas | — |
| notes | Notes | — |
| memo | Memo | (dynamic, based on content topic: ai, tech, etc.) |
| misc | Uncategorized | — |

### Metadata Fields (Required)
- `id`: UUID string
- `title`: Document title
- `source_type`: pdf | text | image | voice | docx | url | agent
- `status`: raw | classified | needs_review | reviewed
- `ingested_at`: ISO 8601 timestamp
- `category`: One of the category IDs above
- `tags`: Array of strings

### Distillation Fields (optional, set by classifier for new documents only)
Old documents may not have these fields — all readers use `.get()` with defaults.
- `relevance_score`: 1-10 personal value (1-3 low, 4-6 mid, 7-9 high, 10 critical). Default: 5
- `temporal_type`: `evergreen` (long-lived knowledge) | `time_sensitive` (news, market data). Default: evergreen
- `key_claims`: Array of core assertions (max 5). Default: []

## Wiki Articles

### Structure
```
wiki/{article_type}/{title}_{id[:8]}/
├── document.md      ← Article content (markdown)
└── metadata.json    ← Article metadata with references
```

### Article Types

| Type | Cardinality | Description |
|------|-------------|-------------|
| `summary` | 1:1 per source doc | Concise overview of a single knowledge document |
| `concept` | 1 per concept (canonical) | Key idea explained in depth, continuously updated |
| `connection` | 1 per relationship pair | Analysis of how two concepts relate, continuously updated |
| `insight` | As needed | Distilled insight from Q&A or analysis |
| `qa` | As needed | Valuable question-answer pair worth preserving |
| `lint` | Per lint run | Wiki health check report |

### Governance Rules

1. **summary**: Always create new (one per source document, never duplicated)
2. **concept**: Check if page exists first → UPDATE existing, never create duplicate
3. **connection**: Check if page exists first → UPDATE existing, never create duplicate
4. **When updating**: Merge new info into existing content coherently, don't just append
5. **Contradictions**: Mark inline with `> ⚠️ 矛盾：[old claim] vs [new claim (source, date)]`

### Metadata Fields (Required)
- `id`: UUID string
- `title`: Article title
- `article_type`: One of the types above
- `source_document_ids`: Array of knowledge document IDs this derives from
- `references`: Array of cross-references (see below)
- `created_at`, `updated_at`: ISO 8601 timestamps

### Reference Relations

| Relation | Direction | Use |
|----------|-----------|-----|
| `source` | knowledge → wiki | This article is derived from this knowledge doc |
| `derived_from` | wiki → wiki | This article builds on another wiki article |
| `related_concept` | any → any | Related but not directly derived |
| `supports` | any → any | This evidence supports that claim |
| `contradicts` | any → any | This evidence contradicts that claim |

Each reference: `{target_id, relation, confidence (0.0-1.0)}`

### Summary Field
Every article must have a `summary` — one line, max 150 chars, appears in INDEX.md.
- Good: "Transformer 架构的核心机制：自注意力如何并行处理序列数据"
- Bad: "A summary about transformers"

## Special Files

| File | Purpose | Maintained by |
|------|---------|---------------|
| `wiki/INDEX.md` | LLM-readable catalog of all articles | Auto-generated from DB |
| `data/log.md` | Current week's activity log | System (append-only) |
| `config/SCHEMA.md` | This file — wiki conventions | User + LLM co-evolve |

## Naming Conventions

- Folder names: `{sanitized_title}_{id[:8]}` — Chinese OK, special chars stripped
- File names: always `document.md` and `metadata.json`
- Language: match the source document's language
- Titles: descriptive and specific, not generic

## Agent Workspace

```
data/workspace/
├── drafts/    ← Work in progress, can be promoted to wiki/
├── scripts/   ← Temporary scripts for analysis
└── scratch/   ← Misc intermediate files
```

- NOT in DB, NOT in INDEX.md, NOT scanned by Compiler
- Auto-cleaned after 7 days
- Use `promote_draft_to_wiki` to finalize a draft into a proper wiki article
