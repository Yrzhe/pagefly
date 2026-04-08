"""Document deletion with reference cleanup.

Safety order:
1. Preview — read-only scan of what will be affected
2. Clean wiki references (update files + DB) — non-destructive, just removes links
3. Delete document folder — filesystem
4. Delete DB record — in same transaction as step 3's DB ops
5. Regenerate INDEX.md
6. Activity log
"""

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from src.shared.config import KNOWLEDGE_DIR, RAW_DIR, WIKI_DIR
from src.shared.logger import get_logger
from src.storage import db

logger = get_logger("storage.deletion")


@dataclass
class DeletionPreview:
    """What will happen if a document is deleted."""

    doc_id: str
    doc_title: str
    doc_path: str
    affected_wiki_articles: list[dict] = field(default_factory=list)
    found: bool = True
    error: str = ""

    def summary(self) -> str:
        if not self.found:
            return f"Document not found: {self.doc_id[:8]}"
        parts = [f"Delete: {self.doc_title} ({self.doc_id[:8]})"]
        if self.affected_wiki_articles:
            parts.append(f"Will clean references in {len(self.affected_wiki_articles)} wiki article(s):")
            for a in self.affected_wiki_articles:
                parts.append(f"  - {a['title']} ({a['article_type']})")
        else:
            parts.append("No wiki articles reference this document.")
        return "\n".join(parts)


def preview_deletion(doc_id: str) -> DeletionPreview:
    """Preview what deleting a document would affect. Read-only."""
    # Find the document
    doc_dir, doc_source = _find_document(doc_id)
    if doc_dir is None:
        return DeletionPreview(doc_id=doc_id, doc_title="", doc_path="", found=False)

    # Get title from metadata
    meta = _read_meta(doc_dir)
    title = meta.get("title", doc_dir.name)

    # Find affected wiki articles
    affected = _find_affected_wiki_articles(doc_id)

    return DeletionPreview(
        doc_id=doc_id,
        doc_title=title,
        doc_path=str(doc_dir),
        affected_wiki_articles=affected,
    )


def execute_deletion(doc_id: str) -> str:
    """Execute document deletion with full reference cleanup.

    Returns a summary of what was done.

    Safety order:
    1. Clean wiki references first (non-destructive)
    2. Then delete the document (filesystem + DB)
    """
    # Re-scan to get fresh state
    doc_dir, doc_source = _find_document(doc_id)
    if doc_dir is None:
        return f"Error: document not found: {doc_id[:8]}"

    meta = _read_meta(doc_dir)
    title = meta.get("title", doc_dir.name)

    # Step 1: Clean wiki references (safe — just removing links from other docs)
    affected = _find_affected_wiki_articles(doc_id)
    cleaned_count = 0
    for article_info in affected:
        try:
            _clean_wiki_references(article_info["id"], doc_id)
            cleaned_count += 1
        except Exception as e:
            logger.error(
                "Failed to clean references in wiki article %s: %s",
                article_info["id"][:8], e,
            )
            return (
                f"Error: failed to clean references in '{article_info['title']}'. "
                f"Deletion aborted to prevent inconsistency. Error: {e}"
            )

    # Step 2: Delete document (DB then filesystem)
    try:
        timestamp = db.now_iso()
        with db.transaction() as conn:
            # Log deletion BEFORE removing the document (foreign key requires doc exists)
            conn.execute(
                """INSERT INTO operations_log (document_id, operation, from_path, to_path, details_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    doc_id, "delete", str(doc_dir), "",
                    json.dumps({
                        "title": title,
                        "affected_wiki_articles": len(affected),
                    }, ensure_ascii=False),
                    timestamp,
                ),
            )

            # Now delete from documents table
            conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))

        # Only delete filesystem AFTER DB transaction succeeds
        if doc_dir.exists():
            shutil.rmtree(doc_dir)
            logger.info("Deleted document folder: %s", doc_dir)

    except Exception as e:
        logger.error("Failed to delete document %s: %s", doc_id[:8], e)
        return f"Error: deletion failed: {e}. References were already cleaned from {cleaned_count} wiki articles."

    # Step 3: Regenerate wiki index
    try:
        from src.shared.indexer import generate_wiki_index
        generate_wiki_index()
    except Exception as e:
        logger.warning("Failed to regenerate wiki index after deletion: %s", e)

    # Step 4: Activity log
    from src.shared.activity_log import append_log
    details = f"Deleted: {title}\nCleaned references in {cleaned_count} wiki article(s)"
    append_log("delete", title, details)

    result = f"Deleted: {title} ({doc_id[:8]})"
    if cleaned_count:
        result += f"\nCleaned references in {cleaned_count} wiki article(s)"
    logger.info("Document deleted: %s (%s)", title, doc_id[:8])
    return result


# ── Internal helpers ──

def _find_document(doc_id: str) -> tuple[Path | None, str]:
    """Find a document by ID across raw/ and knowledge/. Returns (path, source)."""
    for root_dir, source in ((KNOWLEDGE_DIR, "knowledge"), (RAW_DIR, "raw")):
        if not root_dir.exists():
            continue
        for meta_path in root_dir.rglob("metadata.json"):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                if meta.get("id") == doc_id:
                    resolved = meta_path.parent.resolve()
                    if not resolved.is_relative_to(root_dir.resolve()):
                        continue
                    return meta_path.parent, source
            except Exception:
                pass
    return None, ""


def _read_meta(doc_dir: Path) -> dict:
    """Read metadata.json from a document folder."""
    meta_path = doc_dir / "metadata.json"
    if meta_path.exists():
        try:
            return json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _find_affected_wiki_articles(doc_id: str) -> list[dict]:
    """Find all wiki articles that reference the given doc_id."""
    affected = []
    if not WIKI_DIR.exists():
        return affected

    for meta_path in WIKI_DIR.rglob("metadata.json"):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("Corrupted wiki metadata (skipped): %s (%s)", meta_path, e)
            continue

        # Check source_document_ids
        sources = meta.get("source_document_ids", [])
        refs = meta.get("references", [])
        ref_targets = [r.get("target_id", "") for r in refs if isinstance(r, dict)]

        if doc_id in sources or doc_id in ref_targets:
            affected.append({
                "id": meta.get("id", ""),
                "title": meta.get("title", meta_path.parent.name),
                "article_type": meta.get("article_type", ""),
                "path": str(meta_path.parent),
            })

    return affected


def _clean_wiki_references(wiki_article_id: str, doc_id_to_remove: str) -> None:
    """Remove a doc_id from a wiki article's source_document_ids and references.
    Updates both filesystem metadata.json and DB."""
    # Find the wiki article folder
    article_dir = None
    for meta_path in WIKI_DIR.rglob("metadata.json"):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("id") == wiki_article_id:
                article_dir = meta_path.parent
                break
        except Exception:
            continue

    if article_dir is None:
        return

    meta_path = article_dir / "metadata.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))

    # Remove from source_document_ids
    old_sources = meta.get("source_document_ids", [])
    new_sources = [s for s in old_sources if s != doc_id_to_remove]

    # Remove from references
    old_refs = meta.get("references", [])
    new_refs = [
        r for r in old_refs
        if isinstance(r, dict) and r.get("target_id") != doc_id_to_remove
    ]

    meta["source_document_ids"] = new_sources
    meta["references"] = new_refs
    meta["updated_at"] = db.now_iso()

    # Update DB first, then filesystem (DB is authoritative)
    db.update_wiki_article(
        wiki_article_id,
        source_document_ids=json.dumps(new_sources),
    )

    # Write updated metadata to disk
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    logger.info(
        "Cleaned references in wiki article %s: removed %d source(s), %d ref(s)",
        wiki_article_id[:8],
        len(old_sources) - len(new_sources),
        len(old_refs) - len(new_refs),
    )
