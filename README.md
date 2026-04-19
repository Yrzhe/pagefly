<div align="center">

<img src="docs/assets/readme/OG Image.png" alt="PageFly — Personal Knowledge OS" width="720" />

# PageFly

[![MIT License](https://img.shields.io/badge/license-MIT-F59E0B?style=flat-square)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![React](https://img.shields.io/badge/react-19-61DAFB?style=flat-square&logo=react&logoColor=white)](https://react.dev)
[![Docker](https://img.shields.io/badge/docker-ready-2496ED?style=flat-square&logo=docker&logoColor=white)](https://docker.com)

[Live Demo](https://pagefly.ink) · [The Story](#the-story) · [Quick Start](#quick-start) · [中文](README_CN.md)

</div>

---

<div align="center">
  <img src="docs/assets/readme/idea.png" alt="PageFly Concept" width="720" />
  <br />
  <sub>The idea: a knowledge flywheel that grows structured knowledge from the stream of daily life.</sub>
</div>

---

## What is PageFly?

PageFly is a **self-hosted, private knowledge data platform** — a structured, automated, API-ready knowledge governance system with warm, opinionated architecture.

You send it raw material (PDFs, markdown, images, voice memos, URLs, Telegram messages), and it:

1. **Captures** — ingests into a structured raw layer with metadata
2. **Distills** — AI classifies, scores relevance, tags temporal type, extracts key claims
3. **Compiles** — agents write and maintain wiki articles (concept pages, summaries, connection maps)
4. **Serves** — REST API, Telegram bot, Obsidian-compatible markdown output

You never write the wiki manually — the LLM owns it.

## The Story

PageFly was inspired by [Andrej Karpathy's LLMWiki](https://x.com/karpathy/status/1039944530988847617) — the idea that structured knowledge compilation can be automated.

I saw the tweet and thought: what if we took this further? Not just a wiki, but a complete **capture-to-serve pipeline** with ingestion, distillation, governance, and API access.

<div align="center">

**[See my reply to Karpathy →](https://x.com/yrzhe_top/status/2039944530988847617)**

</div>

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
   │  Voice · URL · Text │           │  Query (search + chat)  │
   │                     │           │  Review (lint + audit)   │
   └──────────┬──────────┘           └────────────┬───────────┘
              │                                   │
   ┌──────────▼──────────┐           ┌────────────▼───────────┐
   │   Governance        │           │    Storage              │
   │                     │           │                         │
   │  Classifier (AI)    │           │  SQLite (metadata)      │
   │  Organizer          │           │  Filesystem (documents) │
   │  Integrity Checker  │           │  Wiki (markdown)        │
   └─────────────────────┘           └─────────────────────────┘
```

## Features

| Feature | Description |
|---------|-------------|
| **Multi-format Ingestion** | PDF, DOCX, images (OCR), voice (transcription), URLs, plain text |
| **AI Distillation** | Auto-classification, relevance scoring (1-10), temporal tagging, key claim extraction |
| **Wiki Compilation** | Agents write concept pages, summaries, and connection maps with update-first governance |
| **Telegram Bot** | Send anything via Telegram — text, photos, voice, documents. Inline approval flow |
| **REST API** | Full API with multi-token auth (master + scoped client tokens) |
| **Obsidian-Compatible** | Wiki output as flat `.md` files with YAML frontmatter — drop into any PKM tool |

## Quick Start

### Option A — One-click deploy (Railway)

[![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/new/template?template=https%3A%2F%2Fgithub.com%2FYrzhe%2Fpagefly)

Set `ANTHROPIC_API_KEY`, `PAGEFLY_EMAIL`, and `PAGEFLY_PASSWORD` in the Railway dashboard. Add a volume mounted at `/app/data` for persistence.

### Option B — Docker (local / self-host)

**Prerequisites**: Docker + Docker Compose, an [Anthropic API key](https://console.anthropic.com/).

```bash
git clone https://github.com/Yrzhe/pagefly.git
cd pagefly
python -m src.cli setup      # interactive: email, password, API keys, demo data
docker compose up -d
```

The `setup` command generates a valid `config.json` with a hashed password and — if you accept — seeds a working demo knowledge base so you can see the system in action before adding your own documents.

**Already configured?** Skip `setup` and just `docker compose up -d`.

### Option C — Minimal env-only boot

No `config.json` needed. Export three env vars and launch:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export PAGEFLY_EMAIL=you@example.com
export PAGEFLY_PASSWORD=your-password
docker compose up -d
```

### Access

- **Web UI**: `http://localhost` (or your configured port)
- **API / Swagger**: `http://localhost:8000/docs`
- **Telegram**: Message your bot to start ingesting (if configured)

### Load demo data anytime

```bash
python -m src.cli load-demo     # adds 3 sample docs + 5 wiki articles
python -m src.cli clear-demo    # removes them
```

## Clients

The server runs on its own — the clients below are optional add-ons that capture content into your PageFly instance.

### Browser extension (Chrome / Edge / Brave / Arc)

One-click clip the page you're reading into your knowledge base.

Path: `browser-extension/` (Manifest V3, unpacked load).

```
1. Open chrome://extensions (or the equivalent in your Chromium browser)
2. Enable "Developer mode" (top-right toggle)
3. "Load unpacked" → pick the browser-extension/ folder of this repo
4. Click the extension icon → set Server URL = https://api.your-domain
   and paste your API token from the server's settings page
5. On any web page, click the extension icon → "Clip this page"
```

Firefox / Safari are not supported yet (V3 nuances differ enough to need their own builds).

### macOS desktop capture

Menu-bar app that captures your active app + window context every few seconds and lets you record meeting audio that gets transcribed server-side.

Path: `desktop-capture/` (Swift / SwiftUI, Xcode 15+).

**Build a personal-use copy**:
```bash
cd desktop-capture
./scripts/package-local.sh
# → produces dist/PageflyCapture-<version>.dmg
open dist/PageflyCapture-*.dmg
# Drag PageflyCapture.app into Applications
xattr -dr com.apple.quarantine /Applications/PageflyCapture.app   # ad-hoc signed; clears Gatekeeper warning
```

Open PageflyCapture from Applications → menu bar icon appears → click → **Preferences** → enter `https://api.your-domain` + API token → grant **Accessibility** + **Microphone** in System Settings → Privacy when prompted. The icon turns green once everything is wired.

The script auto-picks any `Apple Development` or `Developer ID Application` cert in your login keychain (stable identity → TCC keeps your grants across rebuilds). With no cert it falls back to ad-hoc, which works but re-prompts for permissions on every reinstall.

For shipping signed + notarized builds to other people, see `desktop-capture/scripts/release.sh` (requires a paid Apple Developer ID).

## Tech Stack

### Backend
| Layer | Choice |
|-------|--------|
| Runtime | Python 3.11+ |
| API | FastAPI |
| Database | SQLite |
| AI Agents | Claude Agent SDK (Anthropic) |
| Scheduler | APScheduler |
| Bot | python-telegram-bot |

### Frontend
| Layer | Choice |
|-------|--------|
| Framework | React + Vite + TypeScript |
| Styling | Tailwind CSS v4 + shadcn/ui |
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
│   ├── agents/          # Compiler, Query, Review agents (Claude SDK)
│   ├── channels/        # Telegram bot, REST API
│   ├── governance/      # Classifier, Organizer, Integrity checker
│   ├── ingest/          # Pipeline + converters (PDF, DOCX, voice, image, URL)
│   ├── scheduler/       # Cron jobs, inbox watcher
│   ├── shared/          # Config, indexer, activity log, types
│   └── storage/         # SQLite DB, deletion logic
├── config/
│   ├── SCHEMA.md        # Wiki conventions (injected into agent prompts)
│   └── skills/          # Agent skill definitions
├── frontend/            # React + Vite + Tailwind
├── data/                # Runtime data (not tracked)
│   ├── raw/             # Ingested documents
│   ├── knowledge/       # Classified & organized
│   └── wiki/            # Compiled articles
├── docker-compose.yml
└── Dockerfile
```

## Links

- **Author**: [@yrzhe_top](https://x.com/yrzhe_top)
- **The Tweet**: [Reply to Karpathy](https://x.com/yrzhe_top/status/2039944530988847617)
- **Inspired by**: [Karpathy's LLMWiki](https://x.com/karpathy/status/1039944530988847617)
- **Live**: [pagefly.ink](https://pagefly.ink)

## License

[MIT](LICENSE) — do whatever you want with it.

---

<div align="center">
  <sub>Built by <a href="https://x.com/yrzhe_top">yrzhe</a> with Claude, one conversation at a time.</sub>
</div>
