<div align="center">

<img src="docs/assets/readme/OG Image.png" alt="PageFly — Personal Knowledge OS" width="720" />

# PageFly

**Your knowledge, structured by AI — capture anything, let agents compile the wiki.**

[![MIT License](https://img.shields.io/badge/license-MIT-F59E0B?style=flat-square)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![React](https://img.shields.io/badge/react-19-61DAFB?style=flat-square&logo=react&logoColor=white)](https://react.dev)
[![Docker](https://img.shields.io/badge/docker-ready-2496ED?style=flat-square&logo=docker&logoColor=white)](https://docker.com)

[Live Demo](https://pagefly.ink) · [Quick Start](#quick-start) · [The Story](#the-story) · [中文](README_CN.md)

</div>

---

```bash
git clone https://github.com/Yrzhe/pagefly.git && cd pagefly
python -m src.cli setup          # interactive: email, password, API keys
docker compose up -d             # → http://localhost
```

---

<div align="center">
  <img src="docs/assets/readme/idea.png" alt="PageFly Concept" width="720" />
  <br />
  <sub>The idea: a knowledge flywheel that grows structured knowledge from the stream of daily life.</sub>
</div>

<!-- TODO: Replace with GIF demo once recorded -->

---

## What is PageFly?

PageFly is a **self-hosted, private knowledge platform** — a structured, automated, API-ready system that turns raw information into compiled knowledge.

You send it raw material (PDFs, markdown, images, voice memos, URLs, Telegram messages), and it:

1. **Captures** — ingests into a structured raw layer with metadata
2. **Distills** — AI classifies, scores relevance, tags temporal type, extracts key claims
3. **Compiles** — agents write and maintain wiki articles (concept pages, summaries, connection maps)
4. **Serves** — REST API, Telegram bot, web frontend, Obsidian-compatible markdown output

You never write the wiki manually — the LLM owns it.

## Features

| Feature | Description |
|---------|-------------|
| **Multi-format Ingestion** | PDF, DOCX, images (OCR), voice (transcription), URLs, plain text |
| **AI Distillation** | Auto-classification, relevance scoring, temporal tagging, key claim extraction |
| **Wiki Compilation** | Agents write concept pages, summaries, connection maps with update-first governance |
| **Workspace Editor** | Tiptap rich-text editor with images, tables, code blocks — draft → finish → ingest to knowledge base |
| **Telegram Bot** | Send anything via Telegram — text, photos, voice, documents. Inline approval flow |
| **Daily Roam** | Random knowledge resurfacing with staleness weighting and dedup |
| **REST API** | ~60 endpoints with multi-token auth (JWT + API tokens + master token) |
| **Scheduled Agents** | Cron-driven review, compilation, linking, trend analysis, daily roam |
| **Knowledge Graph** | Interactive force-directed graph of documents and wiki articles |
| **Obsidian-Compatible** | Wiki output as flat `.md` files with YAML frontmatter — drop into any PKM tool |

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Channels                              │
│  Telegram Bot  ·  REST API  ·  Web Frontend  ·  Scheduler   │
└─────────────┬───────────────────────────────────┬───────────┘
              │                                   │
   ┌──────────▼──────────┐           ┌────────────▼───────────┐
   │   Ingest Pipeline   │           │    Agent System         │
   │                     │           │                         │
   │  PDF · DOCX · Image │           │  Compiler (wiki write)  │
   │  Voice · URL · Text │           │  Linker (connections)   │
   └──────────┬──────────┘           │  Trend (insights)       │
              │                      │  Review (lint + audit)   │
   ┌──────────▼──────────┐           │  Query (search + chat)  │
   │   Governance        │           └────────────┬───────────┘
   │                     │                        │
   │  Classifier (AI)    │           ┌────────────▼───────────┐
   │  Organizer          │           │    Storage              │
   │  Integrity Checker  │           │                         │
   └─────────────────────┘           │  SQLite (metadata)      │
                                     │  Filesystem (documents) │
                                     │  Wiki (markdown)        │
                                     └─────────────────────────┘
```

## The Story

PageFly was inspired by [Andrej Karpathy's LLMWiki](https://x.com/karpathy/status/1039944530988847617) — the idea that structured knowledge compilation can be automated.

I saw the tweet and thought: what if we took this further? Not just a wiki, but a complete **capture-to-serve pipeline** with ingestion, distillation, governance, and API access — plus a workspace where you write alongside AI agents.

## Quick Start

### Option A — Docker (recommended)

**Prerequisites**: Docker + Docker Compose, an [Anthropic API key](https://console.anthropic.com/).

```bash
git clone https://github.com/Yrzhe/pagefly.git
cd pagefly
python -m src.cli setup      # interactive: email, password, API keys, demo data
docker compose up -d
```

The `setup` command generates a valid `config.json` with a hashed password and — if you accept — seeds a working demo knowledge base so you can see the system in action before adding your own documents.

**Already configured?** Skip `setup` and just `docker compose up -d`.

### Option B — Minimal env-only boot

No `config.json` needed. Export three env vars and launch:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export PAGEFLY_EMAIL=you@example.com
export PAGEFLY_PASSWORD=your-password
docker compose up -d
```

### Option C — One-click deploy (Railway)

[![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/new/template?template=https%3A%2F%2Fgithub.com%2FYrzhe%2Fpagefly)

Set `ANTHROPIC_API_KEY`, `PAGEFLY_EMAIL`, and `PAGEFLY_PASSWORD` in the Railway dashboard. Add a volume mounted at `/app/data` for persistence.

### Access

- **Web UI**: `http://localhost` (or your configured domain)
- **API**: `http://localhost:8000/api` — all endpoints documented
- **Telegram**: Message your bot to start ingesting (if configured)

### Load demo data anytime

```bash
python -m src.cli load-demo     # adds 3 sample docs + 5 wiki articles
python -m src.cli clear-demo    # removes them
```

## API Overview (~60 endpoints)

| Category | Endpoints | Description |
|----------|-----------|-------------|
| Knowledge | 14 | Ingest, list, read, update, delete, download documents |
| Wiki | 2 | List and read compiled wiki articles |
| Workspace | 8 | Rich-text documents with status flow (draft → finished → ingest) |
| Search & Query | 3 | Full-text search, agent Q&A, knowledge graph |
| Chat | 3 | Shared conversation (synced with Telegram) |
| Schedules | 6 | Cron task management with run history |
| Activity | 5 | Desktop capture events and audio upload |
| Roam | 1 | Random knowledge resurfacing |
| Categories | 3 | Dynamic category management |
| System | 7 | Stats, trends, tokens, health, demo data |

Auth: Bearer token (JWT from login, API token, or master token).

## Clients

The server runs on its own — the clients below are optional add-ons that capture content into your PageFly instance.

### Browser extension (Chrome / Edge / Brave / Arc)

One-click clip the page you're reading into your knowledge base.

Path: `browser-extension/` (Manifest V3, unpacked load).

```
1. Open chrome://extensions → enable "Developer mode"
2. "Load unpacked" → pick the browser-extension/ folder
3. Click icon → set Server URL + API token
4. On any page: click icon → "Clip this page"
```

### macOS desktop capture

Menu-bar app that captures your active app + window context every few seconds and records meeting audio that gets transcribed server-side.

Path: `desktop-capture/` (Swift / SwiftUI, Xcode 15+).

```bash
cd desktop-capture && ./scripts/package-local.sh
# → dist/PageflyCapture-<version>.dmg
```

Open PageflyCapture → menu bar icon → Preferences → enter server URL + API token → grant Accessibility + Microphone.

## Tech Stack

### Backend
| Layer | Choice |
|-------|--------|
| Runtime | Python 3.11+ |
| API | FastAPI |
| Database | SQLite (WAL mode) |
| AI Agents | Claude Agent SDK (Anthropic) |
| Scheduler | APScheduler |
| Bot | python-telegram-bot |

### Frontend
| Layer | Choice |
|-------|--------|
| Framework | React 19 + Vite + TypeScript |
| Editor | Tiptap (ProseMirror) |
| Styling | Tailwind CSS v4 |
| Router | react-router-dom v6 |
| Icons | Lucide React |

### AI Models
| Task | Model |
|------|-------|
| Classification & Agents | Claude (Anthropic) |
| Voice Transcription | gpt-4o-transcribe (OpenAI) |
| Image OCR | mistral-ocr-latest + mistral-small-latest |

## Project Structure

```
pagefly/
├── src/
│   ├── agents/          # Compiler, Linker, Trend, Query, Review (Claude SDK)
│   ├── channels/        # Telegram bot, REST API
│   ├── governance/      # Classifier, Organizer, Integrity checker
│   ├── ingest/          # Pipeline + converters (PDF, DOCX, voice, image, URL)
│   ├── scheduler/       # Cron jobs, inbox watcher
│   ├── shared/          # Config, roam, indexer, types
│   ├── storage/         # SQLite DB, deletion logic
│   └── auth/            # JWT, TOTP 2FA, email verification
├── config/
│   ├── SCHEMA.md        # Wiki conventions (injected into agent prompts)
│   └── skills/          # Agent skill definitions
├── frontend/            # React + Vite + Tailwind + Tiptap
├── browser-extension/   # Chrome extension (Manifest V3)
├── desktop-capture/     # macOS menu bar app (Swift)
├── data/                # Runtime data (not tracked)
│   ├── raw/             # Ingested documents
│   ├── knowledge/       # Classified & organized
│   ├── wiki/            # Compiled articles
│   └── workspace/       # Editor images
├── docker-compose.yml
└── Dockerfile           # Multi-stage (Python + Node frontend build)
```

## Links

- **Author**: [@yrzhe_top](https://x.com/yrzhe_top)
- **Live**: [pagefly.ink](https://pagefly.ink)
- **Inspired by**: [Karpathy's LLMWiki](https://x.com/karpathy/status/1039944530988847617)

## License

[MIT](LICENSE) — do whatever you want with it.

---

<div align="center">
  <sub>Built by <a href="https://x.com/yrzhe_top">yrzhe</a> with Claude, one conversation at a time.</sub>
</div>
