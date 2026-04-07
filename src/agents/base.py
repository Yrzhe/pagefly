"""Shared agent setup — env configuration and common tool definitions."""

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
    doc_dir = KNOWLEDGE_DIR / rel_path
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


VALID_ARTICLE_TYPES = {"summary", "concept", "connection"}
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
        "Write a compiled article to wiki/. Provide: article_type (summary|concept|connection), "
        "title, content (markdown), source_doc_ids (list of source knowledge document IDs), "
        "and references (list of {target_id, relation, confidence}). "
        "Relation types: source (from knowledge), derived_from (from wiki), "
        "related_concept, supports, contradicts. "
        "All IDs in source_doc_ids and references.target_id are validated against existing documents. "
        "Invalid references will be dropped with warnings."
    ),
    {"article_type": str, "title": str, "content": str, "source_doc_ids": list, "references": list},
)
async def write_wiki_article(args):
    """Write a compiled article to wiki/ with full validation."""
    from src.ingest.metadata import generate_id, now_iso
    from src.storage import db

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

    article_id = generate_id()
    timestamp = now_iso()

    # Create wiki article folder
    sanitized_title = "".join(c for c in title if c not in r'\/:*?"<>|')[:60].strip()
    folder_name = f"{sanitized_title}_{article_id[:8]}"
    article_dir = WIKI_DIR / article_type / folder_name

    # Write document.md
    md_path = article_dir / "document.md"
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(content, encoding="utf-8")

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

    # Validate JSON serialization before writing
    try:
        meta_json = json.dumps(metadata, ensure_ascii=False, indent=2)
        json.loads(meta_json)  # round-trip check
    except (TypeError, ValueError) as e:
        logger.error("metadata.json serialization failed: %s", e)
        return {"content": [{"type": "text", "text": f"Error: metadata JSON serialization failed: {e}"}]}

    meta_path = article_dir / "metadata.json"
    meta_path.write_text(meta_json, encoding="utf-8")

    # Record in database
    conn = db.get_connection()
    conn.execute(
        """INSERT INTO wiki_articles (id, title, article_type, file_path, source_document_ids, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (article_id, title, article_type, str(article_dir), json.dumps(valid_source_ids), timestamp, timestamp),
    )
    conn.commit()
    conn.close()

    warnings = []
    if dropped_sources:
        warnings.append(f"Dropped {len(dropped_sources)} invalid source IDs")
    if len(valid_refs) < len(references):
        warnings.append(f"Dropped {len(references) - len(valid_refs)} invalid references")

    result_msg = f"Article written: {article_dir} (id={article_id[:8]}, refs={len(valid_refs)})"
    if warnings:
        result_msg += "\nWarnings: " + "; ".join(warnings)

    logger.info("Wiki article written: %s (%s, refs=%d)", title, article_type, len(valid_refs))
    return {"content": [{"type": "text", "text": result_msg}]}


@tool(
    "list_wiki_articles",
    "List all existing wiki articles with their metadata.",
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


def build_knowledge_tools_server():
    """Create MCP server with all knowledge/wiki tools."""
    return create_sdk_mcp_server(
        name="pagefly-tools",
        version="1.0.0",
        tools=[list_knowledge_docs, read_document, write_wiki_article, list_wiki_articles],
    )


def build_agent_options(
    skill_name: str,
    extra_system: str = "",
    max_turns: int = 50,
) -> ClaudeAgentOptions:
    """Build ClaudeAgentOptions with skill prompt, tools, and model config."""
    setup_env()

    system_prompt = load_skill_prompt(skill_name)
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
            "mcp__pagefly__write_wiki_article",
            "mcp__pagefly__list_wiki_articles",
        ],
        permission_mode="bypassPermissions",
        max_turns=max_turns,
    )
