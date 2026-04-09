"""Shared agent setup — env configuration and common tool definitions."""

import asyncio
import json
import os
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, tool, create_sdk_mcp_server

from src.shared.config import (
    ANTHROPIC_API_KEY,
    ANTHROPIC_BASE_URL,
    AGENT_MODEL,
    KNOWLEDGE_DIR,
    WIKI_DIR,
    load_skill,
)
from src.shared.logger import get_logger
from src.ingest.metadata import read_metadata

logger = get_logger("agents.base")

# Queue for files that agent wants to send to the user.
# Telegram handler consumes this after agent finishes.
file_send_queue: asyncio.Queue[Path] = asyncio.Queue()


def setup_env() -> None:
    """Set environment variables for Agent SDK from config.json."""
    os.environ["ANTHROPIC_API_KEY"] = ANTHROPIC_API_KEY
    if ANTHROPIC_BASE_URL and ANTHROPIC_BASE_URL != "https://api.anthropic.com":
        os.environ["ANTHROPIC_BASE_URL"] = ANTHROPIC_BASE_URL
    logger.info("Agent env configured (base_url=%s)", ANTHROPIC_BASE_URL)


def load_skill_prompt(skill_name: str) -> str:
    """Load a skill's SKILL.md as system prompt, stripping frontmatter."""
    raw = load_skill(skill_name)
    # Strip YAML frontmatter if present
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) >= 3:
            return parts[2].strip()
    return raw


# ── Common tools for knowledge/wiki operations ──

@tool(
    "list_knowledge_docs",
    "List all document folders in knowledge/ with their metadata. Returns a JSON array of {id, title, category, subcategory, tags, location}.",
    {},
)
async def list_knowledge_docs(args):
    """List all document folders in knowledge/."""
    docs = []
    if not KNOWLEDGE_DIR.exists():
        return {"content": [{"type": "text", "text": "[]"}]}

    for meta_path in sorted(KNOWLEDGE_DIR.rglob("metadata.json")):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            docs.append({
                "id": meta.get("id", ""),
                "title": meta.get("title", ""),
                "category": meta.get("category", ""),
                "subcategory": meta.get("subcategory", ""),
                "tags": meta.get("tags", []),
                "location": str(meta_path.parent.relative_to(KNOWLEDGE_DIR)),
            })
        except Exception as e:
            logger.warning("Failed to read metadata: %s (%s)", meta_path, e)

    return {"content": [{"type": "text", "text": json.dumps(docs, ensure_ascii=False, indent=2)}]}


@tool(
    "read_document",
    "Read a document's markdown content by its folder path relative to knowledge/. Example: 'ideas/斯坦福创业课_528d9736'",
    {"path": str},
)
async def read_document(args):
    """Read a document's content from knowledge/."""
    rel_path = args["path"]
    doc_dir = (KNOWLEDGE_DIR / rel_path).resolve()
    if not doc_dir.is_relative_to(KNOWLEDGE_DIR.resolve()):
        return {"content": [{"type": "text", "text": "Error: path outside knowledge/"}]}
    md_path = doc_dir / "document.md"

    if not md_path.exists():
        return {"content": [{"type": "text", "text": f"Error: document not found at {rel_path}"}]}

    content = md_path.read_text(encoding="utf-8")

    # Also include metadata
    meta_path = doc_dir / "metadata.json"
    meta = {}
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))

    result = {
        "metadata": meta,
        "content": content,
    }
    return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]}


def _collect_all_doc_ids() -> set[str]:
    """Scan knowledge/ and wiki/ to collect all existing document IDs."""
    ids = set()
    for root_dir in (KNOWLEDGE_DIR, WIKI_DIR):
        if not root_dir.exists():
            continue
        for meta_path in root_dir.rglob("metadata.json"):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                doc_id = meta.get("id", "")
                if doc_id:
                    ids.add(doc_id)
            except Exception:
                pass
    return ids


VALID_ARTICLE_TYPES = {"summary", "concept", "connection", "insight", "qa", "lint", "review"}


def _yaml_escape(value: str) -> str:
    """Escape a string for safe YAML double-quoted value."""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").strip()


def _build_frontmatter(title: str, article_type: str, summary: str, source_titles: list[str], timestamp: str) -> str:
    """Build YAML frontmatter for Obsidian compatibility."""
    date = timestamp[:10] if timestamp else ""
    safe_title = _yaml_escape(title)
    safe_summary = _yaml_escape(summary)
    safe_sources = [_yaml_escape(s) for s in source_titles[:10]]
    sources_yaml = ", ".join(f'"{s}"' for s in safe_sources) if safe_sources else ""
    lines = [
        "---",
        f"title: \"{safe_title}\"",
        f"type: {article_type}",
        f"summary: \"{safe_summary}\"",
    ]
    if sources_yaml:
        lines.append(f"sources: [{sources_yaml}]")
    lines.append(f"date: {date}")
    lines.append("---")
    return "\n".join(lines)
VALID_RELATIONS = {"source", "derived_from", "related_concept", "supports", "contradicts"}


def _validate_wiki_article(args: dict, known_ids: set[str]) -> list[str]:
    """Validate write_wiki_article input. Returns list of errors (empty = valid)."""
    errors = []

    # Required fields
    for field in ("article_type", "title", "content", "source_doc_ids"):
        if not args.get(field):
            errors.append(f"Missing required field: {field}")

    # article_type
    if args.get("article_type") and args["article_type"] not in VALID_ARTICLE_TYPES:
        errors.append(f"Invalid article_type: {args['article_type']}. Must be one of {VALID_ARTICLE_TYPES}")

    # source_doc_ids must all exist
    for src_id in args.get("source_doc_ids", []):
        if not isinstance(src_id, str):
            errors.append(f"source_doc_id must be string, got: {type(src_id).__name__}")
        elif src_id not in known_ids:
            errors.append(f"source_doc_id not found: {src_id}")

    # Validate each reference
    for i, ref in enumerate(args.get("references", [])):
        if not isinstance(ref, dict):
            errors.append(f"references[{i}]: must be an object, got {type(ref).__name__}")
            continue
        if "target_id" not in ref:
            errors.append(f"references[{i}]: missing target_id")
        elif ref["target_id"] not in known_ids:
            errors.append(f"references[{i}]: target_id not found: {ref['target_id']}")
        if ref.get("relation") and ref["relation"] not in VALID_RELATIONS:
            errors.append(f"references[{i}]: invalid relation '{ref['relation']}'. Must be one of {VALID_RELATIONS}")
        if "confidence" in ref:
            try:
                c = float(ref["confidence"])
                if not 0.0 <= c <= 1.0:
                    errors.append(f"references[{i}]: confidence must be 0.0-1.0, got {c}")
            except (TypeError, ValueError):
                errors.append(f"references[{i}]: confidence must be a number")

    return errors


@tool(
    "write_wiki_article",
    (
        "Write or UPDATE a wiki article. "
        "To CREATE: provide article_type, title, content, summary, source_doc_ids, references. "
        "To UPDATE an existing article: also provide update_id (the article's UUID). "
        "When updating, the content REPLACES the old content — you must include the full merged content. "
        "For concept and connection types, ALWAYS check if a related article exists first "
        "(via read_wiki_index or list_wiki_articles) and UPDATE it rather than creating a duplicate. "
        "Article types: summary (1:1 with source doc), concept (canonical, one per concept), "
        "connection (one per relationship pair), insight, qa. "
        "When updating with new info that contradicts old data, mark with: "
        "> ⚠️ 矛盾：[old claim] vs [new claim (source, date)]"
    ),
    {
        "article_type": str, "title": str, "content": str, "summary": str,
        "source_doc_ids": list, "references": list, "update_id": str,
    },
)
async def write_wiki_article(args):
    """Write or update a compiled article in wiki/ with full validation."""
    from src.ingest.metadata import generate_id, now_iso
    from src.storage import db

    update_id = args.get("update_id", "")
    is_update = bool(update_id)

    # Collect all known IDs for validation
    known_ids = _collect_all_doc_ids()

    # Validate input
    errors = _validate_wiki_article(args, known_ids)
    hard_errors = [e for e in errors if "Missing required" in e or "Invalid article_type" in e]
    if hard_errors:
        error_msg = "Validation failed:\n" + "\n".join(f"  - {e}" for e in hard_errors)
        logger.error("write_wiki_article rejected: %s", error_msg)
        return {"content": [{"type": "text", "text": f"Error: {error_msg}"}]}

    article_type = args["article_type"]
    title = args["title"]
    content = args["content"]
    summary = args.get("summary", "")[:150]
    source_doc_ids = args["source_doc_ids"]
    references = args.get("references", [])

    # Filter source_doc_ids: keep only valid ones
    valid_source_ids = [sid for sid in source_doc_ids if sid in known_ids]
    dropped_sources = set(source_doc_ids) - set(valid_source_ids)
    for sid in dropped_sources:
        logger.warning("Dropped invalid source_doc_id: %s", sid)

    # Filter references: keep only valid ones
    valid_refs = []
    for ref in references:
        if not isinstance(ref, dict):
            continue
        target = ref.get("target_id", "")
        relation = ref.get("relation", "")
        if target not in known_ids:
            logger.warning("Dropped reference with unknown target_id: %s", target)
            continue
        if relation not in VALID_RELATIONS:
            logger.warning("Dropped reference with invalid relation: %s", relation)
            continue
        valid_refs.append({
            "target_id": target,
            "relation": relation,
            "confidence": min(1.0, max(0.0, float(ref.get("confidence", 0.5)))),
        })

    # Auto-add source relations for valid source_doc_ids not already referenced
    existing_targets = {r["target_id"] for r in valid_refs}
    for src_id in valid_source_ids:
        if src_id not in existing_targets:
            valid_refs.append({"target_id": src_id, "relation": "source", "confidence": 1.0})

    timestamp = now_iso()

    if is_update:
        # ── UPDATE existing article ──
        article_dir = _find_doc_dir_by_id(update_id)
        if article_dir is None:
            return {"content": [{"type": "text", "text": f"Error: article not found for update: {update_id}"}]}

        article_id = update_id

        # Collect source titles for frontmatter
        source_titles = _collect_source_titles(valid_source_ids)

        # Update document.md with frontmatter
        md_path = article_dir / "document.md"
        frontmatter = _build_frontmatter(title, article_type, summary, source_titles, timestamp)
        md_path.write_text(f"{frontmatter}\n\n{content}", encoding="utf-8")

        # Read existing metadata and merge
        meta_path = article_dir / "metadata.json"
        existing_meta = {}
        if meta_path.exists():
            existing_meta = json.loads(meta_path.read_text(encoding="utf-8"))

        # Merge source_doc_ids (union of old + new)
        old_sources = set(existing_meta.get("source_document_ids", []))
        merged_sources = list(old_sources | set(valid_source_ids))

        # Merge references (keep existing + add new, deduplicate by target_id+relation)
        old_refs = existing_meta.get("references", [])
        ref_keys = {(r["target_id"], r["relation"]) for r in valid_refs}
        for old_ref in old_refs:
            if not isinstance(old_ref, dict):
                continue
            key = (old_ref.get("target_id", ""), old_ref.get("relation", ""))
            if key not in ref_keys:
                valid_refs.append(old_ref)

        metadata = {
            **existing_meta,
            "title": title,
            "article_type": article_type,
            "source_document_ids": merged_sources,
            "references": valid_refs,
            "updated_at": timestamp,
        }
        meta_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

        # Update database
        db.update_wiki_article(
            article_id,
            title=title,
            summary=summary,
            source_document_ids=json.dumps(merged_sources),
        )

        mode = "updated"
    else:
        # ── CREATE new article ──
        article_id = generate_id()

        sanitized_title = "".join(c for c in title if c not in r'\/:*?"<>|')[:60].strip()
        folder_name = f"{sanitized_title}_{article_id[:8]}"
        article_dir = WIKI_DIR / article_type / folder_name

        # Collect source titles for frontmatter
        source_titles = _collect_source_titles(valid_source_ids)

        # Write document.md with frontmatter
        md_path = article_dir / "document.md"
        md_path.parent.mkdir(parents=True, exist_ok=True)
        frontmatter = _build_frontmatter(title, article_type, summary, source_titles, timestamp)
        md_path.write_text(f"{frontmatter}\n\n{content}", encoding="utf-8")

        # Write metadata.json
        metadata = {
            "id": article_id,
            "title": title,
            "article_type": article_type,
            "source_document_ids": valid_source_ids,
            "references": valid_refs,
            "created_at": timestamp,
            "updated_at": timestamp,
        }

        try:
            meta_json = json.dumps(metadata, ensure_ascii=False, indent=2)
            json.loads(meta_json)
        except (TypeError, ValueError) as e:
            logger.error("metadata.json serialization failed: %s", e)
            return {"content": [{"type": "text", "text": f"Error: metadata JSON serialization failed: {e}"}]}

        meta_path = article_dir / "metadata.json"
        meta_path.write_text(meta_json, encoding="utf-8")

        # Record in database (rollback files on failure)
        try:
            with db.transaction() as conn:
                conn.execute(
                    """INSERT INTO wiki_articles (id, title, article_type, file_path, summary, source_document_ids, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (article_id, title, article_type, str(article_dir), summary, json.dumps(valid_source_ids), timestamp, timestamp),
                )
        except Exception as e:
            import shutil
            if article_dir.exists():
                shutil.rmtree(article_dir, ignore_errors=True)
            logger.error("DB insert failed, rolled back wiki article: %s", e)
            return {"content": [{"type": "text", "text": f"Error: DB write failed: {e}"}]}

        mode = "created"

    # Regenerate wiki index
    from src.shared.indexer import generate_wiki_index
    try:
        generate_wiki_index()
    except Exception as e:
        logger.warning("Failed to regenerate wiki index: %s", e)

    # Light integrity check
    from src.shared.integrity import check_document
    integrity = check_document(article_dir)
    if not integrity.ok:
        logger.warning("Integrity issues after write: %s", integrity.summary())

    # Activity log
    from src.shared.activity_log import append_log
    append_log("compile", f"{mode}: {title}", f"type={article_type}, refs={len(valid_refs)}")

    # Record in operations_log for dashboard trends
    try:
        from src.storage import db as _db
        for src_id in valid_source_ids:
            _db.log_operation(src_id, "wiki_compile", to_path=str(article_dir))
    except Exception:
        pass

    warnings = []
    if dropped_sources:
        warnings.append(f"Dropped {len(dropped_sources)} invalid source IDs")
    if len(valid_refs) < len(references):
        warnings.append(f"Dropped {len(references) - len(valid_refs)} invalid references")

    result_msg = f"Article {mode}: {article_dir} (id={article_id[:8]}, refs={len(valid_refs)})"
    if warnings:
        result_msg += "\nWarnings: " + "; ".join(warnings)

    logger.info("Wiki article %s: %s (%s, refs=%d)", mode, title, article_type, len(valid_refs))
    return {"content": [{"type": "text", "text": result_msg}]}


@tool(
    "read_activity_log",
    (
        "Read the current week's activity log (data/log.md). "
        "Shows recent events: ingest, classify, compile, review. "
        "Useful for understanding what happened recently in the knowledge base."
    ),
    {},
)
async def read_activity_log(args):
    """Read the current activity log."""
    from src.shared.activity_log import LOG_PATH

    if not LOG_PATH.exists():
        return {"content": [{"type": "text", "text": "No activity log yet."}]}

    content = LOG_PATH.read_text(encoding="utf-8")
    return {"content": [{"type": "text", "text": content}]}


@tool(
    "read_wiki_index",
    (
        "Read the wiki INDEX.md — a compact overview of all wiki articles and knowledge base stats. "
        "Always read this FIRST before drilling into individual articles. "
        "If INDEX.md doesn't exist yet, it will be generated."
    ),
    {},
)
async def read_wiki_index(args):
    """Read wiki/INDEX.md for quick navigation."""
    from src.shared.indexer import INDEX_PATH, generate_wiki_index

    if not INDEX_PATH.exists():
        generate_wiki_index()

    if not INDEX_PATH.exists():
        return {"content": [{"type": "text", "text": "Wiki index is empty — no articles yet."}]}

    content = INDEX_PATH.read_text(encoding="utf-8")
    return {"content": [{"type": "text", "text": content}]}


@tool(
    "list_wiki_articles",
    "List all existing wiki articles with their metadata. For a quick overview, use read_wiki_index instead.",
    {},
)
async def list_wiki_articles(args):
    """List all wiki articles."""
    articles = []
    if not WIKI_DIR.exists():
        return {"content": [{"type": "text", "text": "[]"}]}

    for meta_path in sorted(WIKI_DIR.rglob("metadata.json")):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            articles.append(meta)
        except Exception as e:
            logger.warning("Failed to read wiki metadata: %s (%s)", meta_path, e)

    return {"content": [{"type": "text", "text": json.dumps(articles, ensure_ascii=False, indent=2)}]}


@tool(
    "search_documents",
    "Search across all knowledge/ and wiki/ documents by keyword. Returns matching documents with snippets.",
    {"keyword": str},
)
async def search_documents(args):
    """Full-text search across knowledge base."""
    keyword = args["keyword"].lower()
    results = []

    for root_dir, doc_type in ((KNOWLEDGE_DIR, "knowledge"), (WIKI_DIR, "wiki")):
        if not root_dir.exists():
            continue
        for md_path in root_dir.rglob("document.md"):
            content = md_path.read_text(encoding="utf-8")
            if keyword not in content.lower():
                continue
            meta_path = md_path.parent / "metadata.json"
            meta = {}
            if meta_path.exists():
                meta = json.loads(meta_path.read_text(encoding="utf-8"))

            # Extract snippet around keyword
            idx = content.lower().index(keyword)
            start = max(0, idx - 100)
            end = min(len(content), idx + len(keyword) + 100)
            snippet = content[start:end].replace("\n", " ")

            results.append({
                "type": doc_type,
                "id": meta.get("id", ""),
                "title": meta.get("title", ""),
                "snippet": f"...{snippet}...",
                "path": str(md_path.parent.relative_to(root_dir)),
            })

    return {"content": [{"type": "text", "text": json.dumps(results, ensure_ascii=False, indent=2)}]}


@tool(
    "update_document_content",
    (
        "Update an existing document's markdown content. Provide doc_id and new_content. "
        "This is a DESTRUCTIVE operation — the agent MUST get user approval before calling this. "
        "Returns the old and new content length for verification."
    ),
    {"doc_id": str, "new_content": str},
)
async def update_document_content(args):
    """Update a document's content (requires prior approval)."""
    from src.channels.approval import request_approval
    from src.ingest.metadata import now_iso
    from src.storage import db

    doc_id = args["doc_id"]
    new_content = args["new_content"]

    # Find the document by ID
    doc_dir = _find_doc_dir_by_id(doc_id)
    if doc_dir is None:
        return {"content": [{"type": "text", "text": f"Error: document not found: {doc_id}"}]}

    md_path = doc_dir / "document.md"
    old_content = md_path.read_text(encoding="utf-8")

    # Build change preview for approval
    meta_path = doc_dir / "metadata.json"
    title = doc_dir.name
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        title = meta.get("title", title)

    old_snippet = old_content[:150].replace("\n", " ")
    new_snippet = new_content[:150].replace("\n", " ")
    preview = (
        f"{len(old_content)} -> {len(new_content)} chars\n"
        f"Before: {old_snippet}...\n"
        f"After: {new_snippet}..."
    )

    approved = await request_approval("update_document_content", doc_id, title, preview)
    if not approved:
        return {"content": [{"type": "text", "text": f"Rejected: user denied update to {doc_id[:8]}"}]}

    md_path.write_text(new_content, encoding="utf-8")

    # Log operation
    db.log_operation(doc_id, "update_content", from_path=str(doc_dir), to_path=str(doc_dir))

    logger.info("Document content updated: %s (%d -> %d chars)", doc_id[:8], len(old_content), len(new_content))
    return {"content": [{"type": "text", "text": f"Updated: {doc_id[:8]} ({len(old_content)} -> {len(new_content)} chars)"}]}


@tool(
    "create_knowledge_doc",
    (
        "Create a new document via the ingest pipeline. The document goes through "
        "classification (category, tags, relevance auto-assigned) and auto-compilation. "
        "Provide: title, content (markdown). Tags are auto-generated by the classifier."
    ),
    {"title": str, "content": str},
)
async def create_knowledge_doc(args):
    """Create a new knowledge document via the ingest pipeline."""
    import tempfile
    from src.ingest.pipeline import ingest
    from src.shared.types import IngestInput

    title = args["title"]
    content = args["content"]
    tags = args.get("tags", [])

    # Write content to a temp file and ingest through the normal pipeline
    # This ensures: raw/ → classifier → knowledge/ → compiler
    sanitized = "".join(c for c in title if c not in r'\/:*?"<>|')[:60].strip() or "untitled"
    tmp_dir = tempfile.mkdtemp(prefix="pagefly_agent_")
    tmp_path = Path(tmp_dir) / f"{sanitized}.md"

    # Prepend title as H1 if not already present
    if not content.startswith("# "):
        content = f"# {title}\n\n{content}"

    tmp_path.write_text(content, encoding="utf-8")

    try:
        input_data = IngestInput(
            type="file",
            file_path=str(tmp_path),
            original_filename=f"{sanitized}.md",
        )
        doc_id = ingest(input_data)
    finally:
        tmp_path.unlink(missing_ok=True)
        Path(tmp_dir).rmdir()

    if doc_id:
        logger.info("Knowledge doc created via pipeline: %s (%s)", title, doc_id[:8])
        return {"content": [{"type": "text", "text": f"Created: {title} (id={doc_id[:8]}). Will be auto-classified and compiled."}]}
    else:
        return {"content": [{"type": "text", "text": f"Error: failed to ingest document '{title}'"}]}



def _collect_source_titles(source_ids: list[str]) -> list[str]:
    """Collect titles for source document IDs (for frontmatter)."""
    titles = []
    for doc_id in source_ids:
        doc_dir = _find_doc_dir_by_id(doc_id)
        if doc_dir is None:
            continue
        meta_path = doc_dir / "metadata.json"
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                title = meta.get("title", "")
                if title:
                    titles.append(title)
            except Exception:
                pass
    return titles


def _find_doc_dir_by_id(doc_id: str) -> Path | None:
    """Find a document folder by its ID across knowledge/ and wiki/.
    Validates that the returned path is actually under a safe root directory."""
    for root_dir in (KNOWLEDGE_DIR, WIKI_DIR):
        if not root_dir.exists():
            continue
        for meta_path in root_dir.rglob("metadata.json"):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                if meta.get("id") == doc_id:
                    resolved = meta_path.parent.resolve()
                    if not resolved.is_relative_to(root_dir.resolve()):
                        logger.warning("Path traversal blocked: %s", resolved)
                        continue
                    return meta_path.parent
            except Exception:
                pass
    return None


@tool(
    "send_document_as_zip",
    "Package a document folder as ZIP and send it to the user. Provide doc_id.",
    {"doc_id": str},
)
async def send_document_as_zip(args):
    """Package and queue a document for sending."""
    from src.shared.packaging import zip_document

    doc_id = args["doc_id"]
    doc_dir = _find_doc_dir_by_id(doc_id)
    if doc_dir is None:
        return {"content": [{"type": "text", "text": f"Error: document not found: {doc_id}"}]}

    try:
        zip_path = zip_document(doc_dir)
        await file_send_queue.put(zip_path)
        logger.info("Queued ZIP for sending: %s", zip_path)
        return {"content": [{"type": "text", "text": f"ZIP ready: {doc_dir.name}.zip"}]}
    except Exception as e:
        return {"content": [{"type": "text", "text": f"Error creating ZIP: {e}"}]}


@tool(
    "send_document_as_pdf",
    "Render a document's markdown as PDF and send it to the user. Provide doc_id.",
    {"doc_id": str},
)
async def send_document_as_pdf(args):
    """Render and queue a PDF for sending."""
    from src.shared.packaging import create_pdf_from_markdown

    doc_id = args["doc_id"]
    doc_dir = _find_doc_dir_by_id(doc_id)
    if doc_dir is None:
        return {"content": [{"type": "text", "text": f"Error: document not found: {doc_id}"}]}

    md_path = doc_dir / "document.md"
    if not md_path.exists():
        return {"content": [{"type": "text", "text": f"Error: no document.md in {doc_dir.name}"}]}

    # Get title from metadata
    meta_path = doc_dir / "metadata.json"
    title = doc_dir.name
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        title = meta.get("title", title)

    try:
        pdf_path = create_pdf_from_markdown(md_path, title)
        await file_send_queue.put(pdf_path)
        logger.info("Queued PDF for sending: %s", pdf_path)
        return {"content": [{"type": "text", "text": f"PDF ready: {title}.pdf"}]}
    except RuntimeError as e:
        # weasyprint not installed — fallback to ZIP
        logger.warning("PDF generation unavailable: %s. Falling back to ZIP.", e)
        from src.shared.packaging import zip_document
        zip_path = zip_document(doc_dir)
        await file_send_queue.put(zip_path)
        return {"content": [{"type": "text", "text": f"PDF unavailable, sent as ZIP: {doc_dir.name}.zip"}]}
    except Exception as e:
        return {"content": [{"type": "text", "text": f"Error creating PDF: {e}"}]}


@tool(
    "add_schedule",
    (
        "Add a new scheduled task. Provide: name (human-readable), cron_expr (cron format), "
        "task_type (review|compiler|custom), prompt (what the task should do). "
        "Example cron: '0 9 * * *' = every day at 9am, '0 9 * * 1' = every Monday at 9am."
    ),
    {"name": str, "cron_expr": str, "task_type": str, "prompt": str},
)
async def add_schedule(args):
    """Add a new scheduled task to the database."""
    from src.ingest.metadata import generate_id
    from src.storage import db

    task_id = generate_id()
    name = args["name"]
    cron_expr = args["cron_expr"]
    task_type = args.get("task_type", "custom")
    prompt = args.get("prompt", "")

    # Validate cron expression
    parts = cron_expr.strip().split()
    if len(parts) != 5:
        return {"content": [{"type": "text", "text": f"Error: invalid cron expression '{cron_expr}'. Must have 5 fields."}]}

    # Validate with APScheduler to catch bad values early
    try:
        from apscheduler.triggers.cron import CronTrigger
        CronTrigger(
            minute=parts[0], hour=parts[1], day=parts[2],
            month=parts[3], day_of_week=parts[4],
        )
    except Exception as e:
        return {"content": [{"type": "text", "text": f"Error: invalid cron expression '{cron_expr}': {e}"}]}

    db.insert_scheduled_task(task_id, name, cron_expr, task_type, prompt)
    logger.info("Schedule added: %s (%s) -> %s", name, cron_expr, task_type)

    return {"content": [{"type": "text", "text": f"Schedule added: {name} (id={task_id[:8]}, cron={cron_expr})"}]}


@tool(
    "list_schedules",
    "List all scheduled tasks (both system defaults and user-defined).",
    {},
)
async def list_schedules(args):
    """List all scheduled tasks."""
    from src.storage import db
    from src.shared.config import (
        SCHEDULE_DAILY_REVIEW, SCHEDULE_WEEKLY_REVIEW,
        SCHEDULE_MONTHLY_REVIEW, SCHEDULE_COMPILER,
    )

    # System defaults
    system = [
        {"name": "Daily Review", "cron": SCHEDULE_DAILY_REVIEW, "type": "review", "source": "system"},
        {"name": "Weekly Review", "cron": SCHEDULE_WEEKLY_REVIEW, "type": "review", "source": "system"},
        {"name": "Monthly Review", "cron": SCHEDULE_MONTHLY_REVIEW, "type": "review", "source": "system"},
        {"name": "Compiler", "cron": SCHEDULE_COMPILER, "type": "compiler", "source": "system"},
    ]

    # User-defined
    user_tasks = db.list_scheduled_tasks()
    user = [
        {
            "id": t["id"][:8],
            "name": t["name"],
            "cron": t["cron_expr"],
            "type": t["task_type"],
            "enabled": bool(t["enabled"]),
            "prompt": t["prompt"][:100] + "..." if len(t["prompt"]) > 100 else t["prompt"],
            "source": "user",
        }
        for t in user_tasks
    ]

    all_tasks = system + user
    return {"content": [{"type": "text", "text": json.dumps(all_tasks, ensure_ascii=False, indent=2)}]}


@tool(
    "update_schedule",
    "Update a user-defined scheduled task. Provide task_id and fields to update (name, cron_expr, prompt, enabled).",
    {"task_id": str, "updates": dict},
)
async def update_schedule(args):
    """Update a scheduled task."""
    from src.storage import db

    task_id = args["task_id"]
    updates = args.get("updates", {})

    # Find full ID
    tasks = db.list_scheduled_tasks()
    full_id = None
    for t in tasks:
        if t["id"].startswith(task_id):
            full_id = t["id"]
            break

    if not full_id:
        return {"content": [{"type": "text", "text": f"Error: task not found: {task_id}"}]}

    allowed = {"name", "cron_expr", "prompt", "enabled", "task_type"}
    filtered = {k: v for k, v in updates.items() if k in allowed}

    if not filtered:
        return {"content": [{"type": "text", "text": "Error: no valid fields to update"}]}

    db.update_scheduled_task(full_id, **filtered)
    logger.info("Schedule updated: %s -> %s", task_id, filtered)

    return {"content": [{"type": "text", "text": f"Schedule updated: {task_id}"}]}


@tool(
    "delete_schedule",
    "Delete a user-defined scheduled task by its ID.",
    {"task_id": str},
)
async def delete_schedule(args):
    """Delete a scheduled task."""
    from src.storage import db

    task_id = args["task_id"]
    tasks = db.list_scheduled_tasks()
    full_id = None
    for t in tasks:
        if t["id"].startswith(task_id):
            full_id = t["id"]
            break

    if not full_id:
        return {"content": [{"type": "text", "text": f"Error: task not found: {task_id}"}]}

    db.delete_scheduled_task(full_id)
    logger.info("Schedule deleted: %s", task_id)

    return {"content": [{"type": "text", "text": f"Schedule deleted: {task_id}"}]}


@tool(
    "save_prompt",
    "Save or update a custom prompt. Provide: name (unique key), content (the prompt text), category (general|review|compiler|query).",
    {"name": str, "content": str, "category": str},
)
async def save_prompt(args):
    """Save or update a custom prompt in the database."""
    from src.ingest.metadata import generate_id
    from src.storage import db

    name = args["name"]
    content = args["content"]
    category = args.get("category", "general")

    prompt_id = generate_id()
    db.upsert_custom_prompt(prompt_id, name, content, category)
    logger.info("Prompt saved: %s (%s)", name, category)

    return {"content": [{"type": "text", "text": f"Prompt saved: {name} (category={category})"}]}


@tool(
    "list_prompts",
    "List all custom prompts, optionally filtered by category.",
    {"category": str},
)
async def list_prompts(args):
    """List custom prompts."""
    from src.storage import db

    category = args.get("category")
    if category == "all" or not category:
        category = None

    prompts = db.list_custom_prompts(category)
    result = [
        {
            "name": p["name"],
            "category": p["category"],
            "preview": p["content"][:100] + "..." if len(p["content"]) > 100 else p["content"],
            "updated_at": p["updated_at"],
        }
        for p in prompts
    ]

    return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}]}


# ── URL fetch tools ──


@tool(
    "fetch_url",
    (
        "Fetch a web page and return its content as markdown. "
        "Uses httpx + readability (fast, works for static pages). "
        "Returns the page title, markdown content, and character count. "
        "You decide what to do with the result: save to workspace, move to raw, or discard. "
        "If the content is too short or empty, try fetch_url_browser instead."
    ),
    {"url": str},
)
async def fetch_url_tool(args):
    """Fetch URL content via httpx + readability."""
    from src.ingest.converters.url import fetch_simple

    url = args["url"]
    try:
        result = fetch_simple(url)
        return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]}
    except Exception as e:
        return {"content": [{"type": "text", "text": f"Fetch failed: {e}. Try fetch_url_browser for JS-heavy pages."}]}


@tool(
    "fetch_url_browser",
    (
        "Fetch a web page using Browser Use Cloud (headless browser). "
        "Use this for JS-rendered pages, SPAs, or pages that fetch_url couldn't handle. "
        "You can provide a custom task_instruction to tell the browser what to extract. "
        "Requires browser_use_cloud API key in config. "
        "Returns the page content as markdown."
    ),
    {"url": str, "task_instruction": str},
)
async def fetch_url_browser_tool(args):
    """Fetch URL content via Browser Use Cloud."""
    from src.ingest.converters.url import fetch_via_buc

    url = args["url"]
    task_instruction = args.get("task_instruction", "")
    try:
        result = fetch_via_buc(url, task_instruction)
        return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]}
    except Exception as e:
        return {"content": [{"type": "text", "text": f"Browser fetch failed: {e}"}]}


# ── Deletion tools ──


@tool(
    "preview_delete_document",
    (
        "Preview what will happen if a document is deleted. Shows affected wiki articles. "
        "This is READ-ONLY — nothing is changed. Use this BEFORE delete_document. "
        "Provide: doc_id (the document's UUID)."
    ),
    {"doc_id": str},
)
async def preview_delete_document(args):
    """Preview deletion impact — read only."""
    from src.storage.deletion import preview_deletion

    preview = preview_deletion(args["doc_id"])
    return {"content": [{"type": "text", "text": preview.summary()}]}


@tool(
    "delete_document",
    (
        "Delete a document and clean all references to it from wiki articles. "
        "This is DESTRUCTIVE — always call preview_delete_document first and get user confirmation. "
        "Provide: doc_id (the document's UUID)."
    ),
    {"doc_id": str},
)
async def delete_document(args):
    """Delete document with full reference cleanup."""
    from src.storage.deletion import execute_deletion

    result = execute_deletion(args["doc_id"])
    return {"content": [{"type": "text", "text": result}]}


# ── Database query tool ──

@tool(
    "query_database",
    (
        "Run a read-only SQL query against the PageFly database. "
        "Tables: documents, operations_log, wiki_articles, scheduled_tasks, custom_prompts, chat_sessions. "
        "Only SELECT queries are allowed. Returns JSON results (max 50 rows)."
    ),
    {"sql": str},
)
async def query_database(args):
    """Run a read-only SQL query with table allowlist."""
    from src.storage.db import get_connection

    ALLOWED_TABLES = {"documents", "operations_log", "wiki_articles", "scheduled_tasks", "chat_sessions"}
    BLOCKED_PATTERNS = {"API_TOKENS", "CUSTOM_PROMPTS", "SQLITE_MASTER", "PRAGMA", "ATTACH", "DETACH"}

    sql = args["sql"].strip()
    sql_upper = sql.upper()

    # Safety: only allow SELECT
    if not sql_upper.startswith("SELECT"):
        return {"content": [{"type": "text", "text": "Error: only SELECT queries are allowed"}]}

    # Safety: block dangerous patterns
    for pattern in BLOCKED_PATTERNS:
        if pattern in sql_upper:
            return {"content": [{"type": "text", "text": f"Error: '{pattern.lower()}' is not allowed"}]}

    # Safety: verify only allowed tables are referenced
    import re
    referenced = set(re.findall(r'\bFROM\s+(\w+)|\bJOIN\s+(\w+)', sql_upper))
    table_names = {t for pair in referenced for t in pair if t}
    unauthorized = table_names - {t.upper() for t in ALLOWED_TABLES}
    if unauthorized:
        return {"content": [{"type": "text", "text": f"Error: unauthorized tables: {unauthorized}"}]}

    try:
        conn = get_connection()
        conn.execute("PRAGMA query_only = ON")
        rows = conn.execute(sql).fetchmany(50)
        results = [dict(r) for r in rows]
        conn.close()
        return {"content": [{"type": "text", "text": json.dumps(results, ensure_ascii=False, indent=2)}]}
    except Exception as e:
        return {"content": [{"type": "text", "text": f"Query failed: {type(e).__name__}"}]}


# ── Workspace tools ──

from src.shared.config import WORKSPACE_DIR


@tool(
    "write_workspace_file",
    (
        "Write a file to the agent workspace (data/workspace/). "
        "Use for drafts, scripts, intermediate work, or scratch content. "
        "Workspace files are NOT tracked in DB, NOT indexed, NOT compiled. "
        "Provide: path (relative to workspace/, e.g. 'drafts/my_analysis.md'), content."
    ),
    {"path": str, "content": str},
)
async def write_workspace_file(args):
    """Write a file to the workspace scratch area."""
    rel_path = args["path"]
    content = args["content"]

    file_path = (WORKSPACE_DIR / rel_path).resolve()
    if not file_path.is_relative_to(WORKSPACE_DIR.resolve()):
        return {"content": [{"type": "text", "text": "Error: path outside workspace"}]}
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")

    logger.info("Workspace file written: %s (%d chars)", rel_path, len(content))
    return {"content": [{"type": "text", "text": f"Written: workspace/{rel_path} ({len(content)} chars)"}]}


@tool(
    "list_workspace_files",
    "List all files in the agent workspace (data/workspace/). Shows path, size, and age.",
    {},
)
async def list_workspace_files(args):
    """List workspace contents."""
    from datetime import datetime, timezone

    if not WORKSPACE_DIR.exists():
        return {"content": [{"type": "text", "text": "Workspace is empty."}]}

    now = datetime.now(timezone.utc).astimezone()
    files = []
    for file_path in sorted(WORKSPACE_DIR.rglob("*")):
        if file_path.is_dir():
            continue
        rel = file_path.relative_to(WORKSPACE_DIR)
        stat = file_path.stat()
        size_kb = stat.st_size / 1024
        mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).astimezone()
        age_days = (now - mtime).days

        files.append({
            "path": str(rel),
            "size": f"{size_kb:.1f}KB",
            "age_days": age_days,
        })

    if not files:
        return {"content": [{"type": "text", "text": "Workspace is empty."}]}

    return {"content": [{"type": "text", "text": json.dumps(files, ensure_ascii=False, indent=2)}]}


@tool(
    "read_workspace_file",
    (
        "Read a file from the agent workspace (data/workspace/). "
        "Provide: path (relative to workspace/, e.g. 'research/notes.md')."
    ),
    {"path": str},
)
async def read_workspace_file(args):
    """Read a file from workspace."""
    rel_path = args["path"]
    file_path = (WORKSPACE_DIR / rel_path).resolve()
    if not file_path.is_relative_to(WORKSPACE_DIR.resolve()):
        return {"content": [{"type": "text", "text": "Error: path outside workspace"}]}
    if not file_path.exists():
        return {"content": [{"type": "text", "text": f"Error: file not found: workspace/{rel_path}"}]}

    content = file_path.read_text(encoding="utf-8")
    return {"content": [{"type": "text", "text": content}]}


@tool(
    "delete_workspace_file",
    (
        "Delete a file or folder from the agent workspace (data/workspace/). "
        "Provide: path (relative to workspace/). Can delete files or entire folders."
    ),
    {"path": str},
)
async def delete_workspace_file(args):
    """Delete a file or folder from workspace."""
    import shutil
    rel_path = args["path"]
    target = (WORKSPACE_DIR / rel_path).resolve()
    if not target.is_relative_to(WORKSPACE_DIR.resolve()):
        return {"content": [{"type": "text", "text": "Error: path outside workspace"}]}
    if target == WORKSPACE_DIR.resolve():
        return {"content": [{"type": "text", "text": "Error: cannot delete workspace root"}]}
    if not target.exists():
        return {"content": [{"type": "text", "text": f"Error: not found: workspace/{rel_path}"}]}

    if target.is_dir():
        shutil.rmtree(target)
        logger.info("Workspace folder deleted: %s", rel_path)
    else:
        target.unlink()
        logger.info("Workspace file deleted: %s", rel_path)

    return {"content": [{"type": "text", "text": f"Deleted: workspace/{rel_path}"}]}


@tool(
    "move_workspace_to_raw",
    (
        "Move a file from workspace to raw/ for proper ingest processing. "
        "The file will go through the normal pipeline: classify → organize → knowledge/. "
        "Provide: path (relative to workspace/), original_filename (for the ingest pipeline)."
    ),
    {"path": str, "original_filename": str},
)
async def move_workspace_to_raw(args):
    """Move a workspace file to raw/ for ingest."""
    rel_path = args["path"]
    original_filename = args.get("original_filename", "")
    source = (WORKSPACE_DIR / rel_path).resolve()
    if not source.is_relative_to(WORKSPACE_DIR.resolve()):
        return {"content": [{"type": "text", "text": "Error: path outside workspace"}]}
    if not source.exists():
        return {"content": [{"type": "text", "text": f"Error: not found: workspace/{rel_path}"}]}

    # Ingest the file through the normal pipeline
    from src.ingest.pipeline import ingest
    from src.shared.types import IngestInput

    input_data = IngestInput(
        type="file",
        file_path=str(source),
        original_filename=original_filename or source.name,
    )
    doc_id = ingest(input_data)

    if doc_id:
        # Remove from workspace after successful ingest
        if source.is_file():
            source.unlink()
        logger.info("Workspace file ingested: %s → raw/ (id=%s)", rel_path, doc_id[:8])
        return {"content": [{"type": "text", "text": f"Ingested: {rel_path} → raw/ (id={doc_id[:8]})"}]}
    else:
        return {"content": [{"type": "text", "text": f"Error: ingest failed for {rel_path}"}]}


@tool(
    "promote_draft_to_wiki",
    (
        "Promote a workspace draft to a wiki article. "
        "Reads the file from workspace, then writes it as a proper wiki article "
        "with full validation, DB tracking, and index update. "
        "Provide: workspace_path (relative to workspace/), article_type, title, summary, source_doc_ids, references. "
        "The workspace file is kept after promotion (not deleted)."
    ),
    {
        "workspace_path": str, "article_type": str, "title": str,
        "summary": str, "source_doc_ids": list, "references": list,
    },
)
async def promote_draft_to_wiki(args):
    """Promote a workspace draft to a full wiki article."""
    ws_path = WORKSPACE_DIR / args["workspace_path"]
    if not ws_path.exists():
        return {"content": [{"type": "text", "text": f"Error: file not found: workspace/{args['workspace_path']}"}]}

    content = ws_path.read_text(encoding="utf-8")

    # Delegate to write_wiki_article by building the args
    wiki_args = {
        "article_type": args["article_type"],
        "title": args["title"],
        "content": content,
        "summary": args.get("summary", ""),
        "source_doc_ids": args.get("source_doc_ids", []),
        "references": args.get("references", []),
    }

    result = await write_wiki_article(wiki_args)

    logger.info("Draft promoted: workspace/%s → wiki", args["workspace_path"])
    return result


def build_knowledge_tools_server():
    """Create MCP server with all knowledge/wiki tools."""
    return create_sdk_mcp_server(
        name="pagefly-tools",
        version="1.0.0",
        tools=[
            list_knowledge_docs,
            read_document,
            read_activity_log,
            read_wiki_index,
            write_wiki_article,
            list_wiki_articles,
            search_documents,
            update_document_content,
            create_knowledge_doc,
            send_document_as_zip,
            send_document_as_pdf,
            add_schedule,
            list_schedules,
            update_schedule,
            delete_schedule,
            save_prompt,
            list_prompts,
            fetch_url_tool,
            fetch_url_browser_tool,
            preview_delete_document,
            delete_document,
            write_workspace_file,
            read_workspace_file,
            delete_workspace_file,
            list_workspace_files,
            move_workspace_to_raw,
            promote_draft_to_wiki,
            query_database,
        ],
    )


def _load_schema() -> str:
    """Load SCHEMA.md if it exists."""
    from src.shared.config import CONFIG_DIR
    schema_path = CONFIG_DIR / "SCHEMA.md"
    if schema_path.exists():
        return schema_path.read_text(encoding="utf-8")
    return ""


def build_agent_options(
    skill_name: str,
    extra_system: str = "",
    max_turns: int = 50,
) -> ClaudeAgentOptions:
    """Build ClaudeAgentOptions with skill prompt, tools, and model config."""
    setup_env()

    system_prompt = load_skill_prompt(skill_name)

    # Inject schema as shared context for all agents
    schema = _load_schema()
    if schema:
        system_prompt = f"{system_prompt}\n\n---\n\n{schema}"

    if extra_system:
        system_prompt = f"{system_prompt}\n\n{extra_system}"

    server = build_knowledge_tools_server()

    return ClaudeAgentOptions(
        model=AGENT_MODEL,
        system_prompt=system_prompt,
        mcp_servers={"pagefly": server},
        allowed_tools=[
            "mcp__pagefly__list_knowledge_docs",
            "mcp__pagefly__read_document",
            "mcp__pagefly__read_activity_log",
            "mcp__pagefly__read_wiki_index",
            "mcp__pagefly__write_wiki_article",
            "mcp__pagefly__list_wiki_articles",
            "mcp__pagefly__search_documents",
            "mcp__pagefly__update_document_content",
            "mcp__pagefly__create_knowledge_doc",
            "mcp__pagefly__send_document_as_zip",
            "mcp__pagefly__send_document_as_pdf",
            "mcp__pagefly__add_schedule",
            "mcp__pagefly__list_schedules",
            "mcp__pagefly__update_schedule",
            "mcp__pagefly__delete_schedule",
            "mcp__pagefly__save_prompt",
            "mcp__pagefly__list_prompts",
            "mcp__pagefly__fetch_url",
            "mcp__pagefly__fetch_url_browser",
            "mcp__pagefly__preview_delete_document",
            "mcp__pagefly__delete_document",
            "mcp__pagefly__write_workspace_file",
            "mcp__pagefly__read_workspace_file",
            "mcp__pagefly__delete_workspace_file",
            "mcp__pagefly__list_workspace_files",
            "mcp__pagefly__move_workspace_to_raw",
            "mcp__pagefly__promote_draft_to_wiki",
            "mcp__pagefly__query_database",
        ],
        permission_mode="bypassPermissions",
        max_turns=max_turns,
    )
