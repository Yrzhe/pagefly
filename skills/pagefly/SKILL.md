# PageFly Knowledge Base

Connect to your self-hosted PageFly knowledge base. Query your documents, search, upload files, and ask your AI agent — all from Claude Code.

## Setup

Set these environment variables or pass as flags:

```bash
export PAGEFLY_URL="https://your-pagefly-instance.com"   # Your PageFly API base URL
export PAGEFLY_TOKEN="pf_your_api_token_here"             # API token from Settings > API & Tokens
```

Or configure in your project's `CLAUDE.md`:
```
PageFly: URL=https://your-instance.com TOKEN=pf_xxx
```

## Commands

### query

Ask a question to your knowledge base agent. The agent searches your documents and returns a grounded answer.

**Usage**: `/pagefly query <question>`

```bash
curl -s -X POST "${PAGEFLY_URL}/api/query" \
  -H "Authorization: Bearer ${PAGEFLY_TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"question\": \"<QUESTION>\"}"
```

**Response**: `{ "question": "...", "answer": "..." }`

Example: `/pagefly query what do I know about transformer architectures`

### search

Search across all documents and wiki articles by keyword.

**Usage**: `/pagefly search <keyword>`

```bash
curl -s -X POST "${PAGEFLY_URL}/api/search" \
  -H "Authorization: Bearer ${PAGEFLY_TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"keyword\": \"<KEYWORD>\"}"
```

**Response**: `{ "keyword": "...", "total": N, "results": [{ "type": "knowledge|wiki", "id": "...", "title": "...", "snippet": "..." }] }`

### list

List documents in your knowledge base. Optionally filter by category.

**Usage**: `/pagefly list [category]`

```bash
curl -s "${PAGEFLY_URL}/api/documents?limit=50" \
  -H "Authorization: Bearer ${PAGEFLY_TOKEN}"
```

With category filter:
```bash
curl -s "${PAGEFLY_URL}/api/documents?category=<CATEGORY>&limit=50" \
  -H "Authorization: Bearer ${PAGEFLY_TOKEN}"
```

**Response**: `{ "documents": [{ "id": "...", "title": "...", "category": "...", "subcategory": "...", "status": "...", "ingested_at": "..." }], "total": N }`

### read

Read the full content of a specific document or wiki article.

**Usage**: `/pagefly read <document_id>`

```bash
curl -s "${PAGEFLY_URL}/api/documents/<ID>" \
  -H "Authorization: Bearer ${PAGEFLY_TOKEN}"
```

**Response**: `{ "id": "...", "title": "...", "content": "...", "category": "...", ... }`

For wiki articles:
```bash
curl -s "${PAGEFLY_URL}/api/wiki/<ID>" \
  -H "Authorization: Bearer ${PAGEFLY_TOKEN}"
```

### upload

Upload a file to your knowledge base. Supports PDF, markdown, text, docx, images, and audio files.

**Usage**: `/pagefly upload <file_path>`

```bash
curl -s -X POST "${PAGEFLY_URL}/api/ingest" \
  -H "Authorization: Bearer ${PAGEFLY_TOKEN}" \
  -F "file=@<FILE_PATH>"
```

**Response**: `{ "doc_id": "...", "title": "...", "message": "..." }`

The file will be automatically converted to markdown, classified, and added to your knowledge base.

### wiki

List all wiki articles compiled by the agent.

**Usage**: `/pagefly wiki`

```bash
curl -s "${PAGEFLY_URL}/api/wiki" \
  -H "Authorization: Bearer ${PAGEFLY_TOKEN}"
```

**Response**: `{ "articles": [{ "id": "...", "title": "...", "article_type": "concept|summary|connection", "created_at": "..." }] }`

### stats

Show knowledge base statistics.

**Usage**: `/pagefly stats`

```bash
curl -s "${PAGEFLY_URL}/api/stats" \
  -H "Authorization: Bearer ${PAGEFLY_TOKEN}"
```

**Response**: `{ "documents": N, "wiki_articles": N, "operations": N, "categories": { "cat1": N, ... } }`

### chat

Send a message to the chat agent (shared with Telegram bot).

**Usage**: `/pagefly chat <message>`

```bash
curl -s -X POST "${PAGEFLY_URL}/api/chat" \
  -H "Authorization: Bearer ${PAGEFLY_TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"message\": \"<MESSAGE>\"}"
```

**Response**: `{ "response": "...", "messages": [...] }`

### graph

Get the knowledge graph data (nodes and edges).

**Usage**: `/pagefly graph`

```bash
curl -s "${PAGEFLY_URL}/api/graph" \
  -H "Authorization: Bearer ${PAGEFLY_TOKEN}"
```

**Response**: `{ "nodes": [{ "id": "...", "label": "...", "type": "document|wiki", "category": "..." }], "edges": [{ "source": "...", "target": "...", "relation": "..." }] }`

## Use Cases

- **Research context**: Before writing code or content, query your knowledge base for relevant background
- **Save findings**: Upload PDFs, articles, or notes you find during work
- **Cross-reference**: Search for connections between topics across your documents
- **Chat**: Ask complex questions that require synthesizing multiple documents
- **Check stats**: See how your knowledge base is growing

## Requirements

- A running PageFly instance (self-hosted via Docker)
- An API token (create one at your PageFly dashboard > API & Tokens)
- `curl` available in the shell (standard on all systems)

## More Info

- GitHub: https://github.com/Yrzhe/pagefly
- Docs: https://pagefly.ink
