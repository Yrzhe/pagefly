# PageFly Implementation Plan

## Phase 1: Core Infrastructure — COMPLETE

### Stage 1.1: Project Scaffolding — COMPLETE
- [x] Python project setup (pyproject.toml)
- [x] Directory structure (src/, config/, data/, tests/, scripts/)
- [x] config.json.example with base_url support for all API providers
- [x] .gitignore, Dockerfile, docker-compose.yml
- [x] GitHub repo created (Yrzhe/pagefly)

### Stage 1.2: Storage Layer — COMPLETE
- [x] `src/storage/files.py` — safe file ops (no delete), move file/directory, write bytes
- [x] `src/storage/db.py` — SQLite with 6 tables:
  - documents, operations_log, wiki_articles
  - scheduled_tasks, custom_prompts
- [x] `src/shared/config.py` — loads from config.json (API keys, base URLs, watcher, scheduler, notifications)
- [x] `src/shared/logger.py` — formatted logging
- [x] `src/shared/types.py` — SourceType, DocumentStatus, ClassificationResult, ConvertResult, ImageAsset, etc.

### Stage 1.3: Metadata Module — COMPLETE
- [x] `src/ingest/metadata.py` — metadata.json generation, validation, read/write/update
- [x] Folder-based document structure: each doc = folder with document.md + metadata.json + images/
- [x] UUID generation, ISO 8601 timestamps

### Stage 1.4: Classification — COMPLETE
- [x] `config/categories.json` — 8 categories with subcategories
- [x] `config/prompts/classifier.md` — external classifier prompt
- [x] `src/governance/classifier.py` — Claude API structured output, retry logic, category validation

### Stage 1.5: Ingest Pipeline — COMPLETE
- [x] `src/ingest/pipeline.py` — unified entry point with converter registration
- [x] `src/ingest/converters/text.py` — text/markdown pass-through
- [x] `src/ingest/converters/pdf.py` — Mistral OCR with retry, image extraction, AI image description
- [x] Title-based folder naming ({title}_{id_short})

### Stage 1.6: Governance — COMPLETE
- [x] `src/governance/organizer.py` — scans raw/, classifies, moves folders to knowledge/
- [x] Confidence threshold (0.8) for auto-classify vs needs_review
- [x] Full database tracking (documents + operations_log)

### Stage 1.7: Docker — COMPLETE (basic)
- [x] Dockerfile with Python 3.11-slim + weasyprint system dependencies
- [x] docker-compose.yml with volume mounts

---

## Phase 2: Agent System — COMPLETE

### Stage 2.1: Compiler Agent — COMPLETE
- [x] `src/agents/base.py` — shared agent setup, env config from config.json, MCP tool server
- [x] `src/agents/compiler.py` — Claude Agent SDK, reads knowledge/, writes wiki/
- [x] Reference system: source_document_ids + references with relation types
- [x] Reference validation: all target_ids verified against existing documents
- [x] JSON round-trip validation on metadata.json
- [x] Wiki article types: summary, concept, connection

### Stage 2.2: Query Agent — COMPLETE
- [x] `src/agents/query.py` — multi-turn conversation, tool call callbacks
- [x] Agent tools: list_knowledge_docs, read_document, search_documents
- [x] Write tools: create_knowledge_doc, update_document_content, write_wiki_article
- [x] File tools: send_document_as_zip, send_document_as_pdf
- [x] Schedule tools: add_schedule, list_schedules, update_schedule, delete_schedule
- [x] Prompt tools: save_prompt, list_prompts

### Stage 2.3: Review Agent — COMPLETE
- [x] `src/agents/review.py` — daily/weekly/monthly review generation
- [x] Per-type prompt files: config/skills/review/{daily,weekly,monthly}.md

---

## Phase 3: Channels & Scheduling — COMPLETE

### Stage 3.1: Telegram Bot — COMPLETE
- [x] `src/channels/telegram.py` — full interactive bot
- [x] Commands: /start, /search, /status, /reset (auto-registered)
- [x] Text messages → Query Agent with multi-turn session
- [x] Document upload → auto ingest
- [x] Real-time UX: continuous typing + live tool call status
- [x] Telegram MarkdownV2 formatting (no tables, mobile-friendly)
- [x] File sending: ZIP and PDF via agent tools

### Stage 3.2: Unified Scheduler — COMPLETE
- [x] `src/scheduler/engine.py` — APScheduler with cron jobs
- [x] `src/scheduler/watcher.py` — inbox/ file watcher with configurable parallel limit
- [x] `src/scheduler/notifier.py` — notification dispatch (Telegram if configured)
- [x] System cron jobs: daily/weekly/monthly review, compiler, chat archive
- [x] User-defined tasks from database (live reload every 60s)
- [x] `src/main.py` — runs scheduler + watcher + Telegram bot together

### Stage 3.3: Dynamic Management — COMPLETE
- [x] DB tables: scheduled_tasks, custom_prompts
- [x] Agent tools for CRUD on schedules and prompts
- [x] Scheduler auto-reloads user tasks from DB

---

## Phase 4: Additional Converters — TODO

### Stage 4.1: Image OCR Converter
**Goal**: Convert images (PNG/JPG) to markdown via Mistral OCR or vision model
**Status**: Not Started
- [ ] `src/ingest/converters/image.py`
- [ ] Support: .png, .jpg, .jpeg, .webp
- [ ] OCR text extraction + image description

### Stage 4.2: Word Document Converter
**Goal**: Convert .docx files to markdown
**Status**: Not Started
- [ ] `src/ingest/converters/docx.py`
- [ ] Extract text, images, and formatting
- [ ] Dependency: python-docx

### Stage 4.3: URL Converter
**Goal**: Scrape web pages and convert to markdown
**Status**: Not Started
- [ ] `src/ingest/converters/url.py`
- [ ] HTML to markdown conversion
- [ ] Handle images and metadata extraction
- [ ] Dependency: httpx + readability/beautifulsoup

### Stage 4.4: Voice Converter
**Goal**: Transcribe audio files to markdown
**Status**: Not Started
- [ ] `src/ingest/converters/voice.py`
- [ ] Support: .mp3, .wav, .ogg, .m4a
- [ ] OpenAI Whisper API for transcription
- [ ] Speaker diarization (optional)

---

## Phase 5: REST API — TODO

### Stage 5.1: FastAPI Core
**Goal**: RESTful API for external integrations
**Status**: Not Started
- [ ] `src/channels/api.py` — FastAPI app
- [ ] POST /ingest — upload files for ingest
- [ ] GET /documents — list documents with filters
- [ ] GET /documents/{id} — get document content + metadata
- [ ] POST /query — send question, get agent response
- [ ] GET /wiki — list wiki articles
- [ ] GET /wiki/{id} — get wiki article content
- [ ] GET /schedules — list scheduled tasks
- [ ] POST /schedules — create scheduled task
- [ ] GET /export/{id} — download document as ZIP or PDF

### Stage 5.2: Authentication
**Status**: Not Started
- [ ] API key authentication
- [ ] Rate limiting

---

## Phase 6: Approval System — TODO

### Stage 6.1: Telegram Approval Flow
**Goal**: Agent requests approval for destructive actions via inline keyboard
**Status**: Not Started
- [ ] Inline keyboard buttons (Approve / Reject)
- [ ] Pending action queue with timeout
- [ ] Agent pauses execution until user approves
- [ ] Actions requiring approval: update content, modify metadata, move documents

---

## Phase 7: Frontend — TODO

### Stage 7.1: Web Dashboard
**Goal**: Browse and manage knowledge base via web UI
**Status**: Not Started
- [ ] Document browser (knowledge/ and wiki/)
- [ ] Document viewer with markdown rendering
- [ ] Search across all documents
- [ ] Schedule manager (CRUD)
- [ ] Prompt editor
- [ ] System stats and activity log

### Stage 7.2: Knowledge Graph Visualization
**Status**: Not Started
- [ ] Interactive graph of document references
- [ ] Filter by category, tags, relation type
- [ ] Click node to view document

---

## Phase 8: Advanced Features — TODO

### Stage 8.1: Linker Agent
**Goal**: Automatically discover connections between documents
**Status**: Not Started
- [ ] `src/agents/linker.py`
- [ ] Scan knowledge/ for related documents
- [ ] Add references to metadata.json
- [ ] config/skills/linker/SKILL.md

### Stage 8.2: Trend Discovery
**Goal**: Identify emerging themes and proactively suggest exploration
**Status**: Not Started
- [ ] Analyze document frequency and tag patterns
- [ ] Push insights to user via Telegram

### Stage 8.3: Multi-user Support
**Status**: Not Started
- [ ] Per-user knowledge bases
- [ ] Access control

---

## Architecture Summary

```
data/inbox/        ← Drop files here (or upload via Telegram/API)
     ↓ watcher (event-driven, parallel limit from config)
data/raw/          ← Ingest pipeline (convert + metadata)
     ↓ classifier + organizer (auto or needs_review)
data/knowledge/    ← Organized documents by category
     ↓ compiler agent (cron)
data/wiki/         ← Compiled articles (summary/concept/connection/review)
     ↓ notifier
Telegram / API     ← User interaction + notifications
```

**Key Principles:**
- Every document = folder (document.md + metadata.json + assets)
- No delete operations — only create, move, update
- All operations logged in database
- References validated before writing
- Config-driven: categories, schedules, prompts all external
- Modular: one file per function, pluggable converters/agents/channels
- System works without Telegram — bot is optional notification channel
