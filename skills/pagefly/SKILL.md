# PageFly — Personal Knowledge Base Skill

Connect to your self-hosted PageFly knowledge base. Query documents, search, upload files, read content, and chat with your AI agent — all from Claude Code.

**Base directory**: The skill scripts are in `skills/pagefly/scripts/` relative to the PageFly repo root.

## Setup

**Option 1: Environment variables** (recommended)
```bash
export PAGEFLY_URL="https://your-instance.com"
export PAGEFLY_TOKEN="pf_your_api_token"
```

**Option 2: Interactive setup**
```bash
python3 skills/pagefly/scripts/setup.py
```
This creates `~/.config/pagefly/config.json` with your URL and token.

**Get your token**: Open your PageFly dashboard → API & Tokens → Create Token → Copy.

## Commands

All commands run Python scripts directly. No dependencies needed beyond Python 3.

### query — Ask your knowledge base

Ask a question. The agent searches your documents and returns a grounded answer with sources.

```bash
python3 skills/pagefly/scripts/query.py "what do I know about transformer architectures"
```

Use when: you need context from your knowledge base before writing code, making a decision, or starting research.

### search — Full-text search

Search across all documents and wiki articles by keyword.

```bash
python3 skills/pagefly/scripts/search.py "reinforcement learning"
```

Returns: type (knowledge/wiki), title, snippet, and document ID for each match.

### list — List documents

List all documents, optionally filtered by category.

```bash
python3 skills/pagefly/scripts/list_docs.py
python3 skills/pagefly/scripts/list_docs.py "machine-learning"
```

### read — Read a document

Read the full markdown content of a document or wiki article.

```bash
python3 skills/pagefly/scripts/read_doc.py <document_id>
python3 skills/pagefly/scripts/read_doc.py <wiki_id> --wiki
```

### upload — Ingest a file

Upload a file to your knowledge base. Supports PDF, markdown, text, docx, images (OCR), and audio (Whisper transcription).

```bash
python3 skills/pagefly/scripts/upload.py ./paper.pdf
python3 skills/pagefly/scripts/upload.py ./meeting-notes.md
python3 skills/pagefly/scripts/upload.py ./whiteboard-photo.jpg
```

The file is automatically converted, classified, and added to your knowledge base.

### wiki — List compiled wiki articles

List all wiki articles that the agent has compiled from your documents.

```bash
python3 skills/pagefly/scripts/wiki.py
```

### chat — Chat with the agent

Send a message to the chat agent. Conversation history is shared with the Telegram bot.

```bash
python3 skills/pagefly/scripts/chat.py "summarize my recent notes on startup strategy"
```

### stats — Knowledge base statistics

Show document count, wiki article count, categories, and more.

```bash
python3 skills/pagefly/scripts/stats.py
```

## Configuration File

After running `setup.py`, config is stored at `~/.config/pagefly/config.json`:

```json
{
  "url": "https://your-instance.com",
  "token": "pf_your_api_token"
}
```

Environment variables `PAGEFLY_URL` and `PAGEFLY_TOKEN` always override the config file.

## Use Cases

- **Before coding**: `query.py "how does our auth system work"` — get context from past documents
- **During research**: `upload.py paper.pdf` — save a paper you found, it gets auto-classified
- **Cross-referencing**: `search.py "attention mechanism"` — find all related docs across your knowledge base
- **Review learning**: `wiki.py` then `read_doc.py <id> --wiki` — read AI-compiled summaries
- **Quick save**: `chat.py "remember: the deadline for the proposal is April 20"` — save a note via chat

## REST API Reference

For advanced usage, the full API is available:

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | /api/query | Agent Q&A (body: {question}) |
| POST | /api/search | Full-text search (body: {keyword}) |
| GET | /api/documents | List documents (?category, ?search, ?limit, ?offset) |
| GET | /api/documents/{id} | Get document metadata + content |
| POST | /api/ingest | Upload file (multipart/form-data) |
| GET | /api/wiki | List wiki articles |
| GET | /api/wiki/{id} | Get wiki article content |
| POST | /api/chat | Chat message (body: {message}) |
| GET | /api/chat/history | Get chat history |
| GET | /api/graph | Knowledge graph nodes + edges |
| GET | /api/stats | System statistics |

All endpoints require `Authorization: Bearer <token>` header.

## Requirements

- Python 3.8+ (no pip packages needed — uses only stdlib)
- A running PageFly instance
- An API token

## Links

- GitHub: https://github.com/Yrzhe/pagefly
- Demo: https://pagefly.ink
