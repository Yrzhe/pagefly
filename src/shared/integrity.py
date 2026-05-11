"""Data integrity checker — verifies filesystem ↔ DB consistency."""

import json
from dataclasses import dataclass, field
from pathlib import Path

from src.shared.config import KNOWLEDGE_DIR, WIKI_DIR
from src.shared.logger import get_logger
from src.storage import db

logger = get_logger("shared.integrity")

REQUIRED_KNOWLEDGE_FIELDS = {"id", "title", "status", "source_type", "ingested_at"}
REQUIRED_WIKI_FIELDS = {"id", "title", "article_type"}


@dataclass
class IntegrityReport:
    """Results of an integrity check."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    auto_fixed: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0

    def summary(self) -> str:
        parts = []
        if self.auto_fixed:
            parts.append(f"Auto-fixed: {len(self.auto_fixed)}")
        if self.warnings:
            parts.append(f"Warnings: {len(self.warnings)}")
        if self.errors:
            parts.append(f"Errors: {len(self.errors)}")
        if not parts:
            return "All checks passed"
        return " | ".join(parts)

    def to_markdown(self) -> str:
        lines = ["# Integrity Check Report", ""]
        if self.ok and not self.warnings and not self.auto_fixed:
            lines.append("All checks passed.")
            return "\n".join(lines)

        if self.auto_fixed:
            lines.append(f"## Auto-fixed ({len(self.auto_fixed)})")
            for item in self.auto_fixed:
                lines.append(f"- {item}")
            lines.append("")

        if self.warnings:
            lines.append(f"## Warnings ({len(self.warnings)})")
            for item in self.warnings:
                lines.append(f"- {item}")
            lines.append("")

        if self.errors:
            lines.append(f"## Errors ({len(self.errors)})")
            for item in self.errors:
                lines.append(f"- {item}")
            lines.append("")

        return "\n".join(lines)


# ── Light check (single document) ──

def check_document(doc_dir: Path) -> IntegrityReport:
    """Verify a single document folder's integrity."""
    report = IntegrityReport()
    name = doc_dir.name

    # 1. document.md exists
    md_path = doc_dir / "document.md"
    if not md_path.exists():
        report.errors.append(f"{name}: missing document.md")

    # 2. metadata.json exists and valid
    meta_path = doc_dir / "metadata.json"
    if not meta_path.exists():
        report.errors.append(f"{name}: missing metadata.json")
        return report

    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        report.errors.append(f"{name}: invalid metadata.json: {e}")
        return report

    # 3. Required fields
    is_wiki = "article_type" in meta
    required = REQUIRED_WIKI_FIELDS if is_wiki else REQUIRED_KNOWLEDGE_FIELDS
    missing = required - set(meta.keys())
    if missing:
        report.warnings.append(f"{name}: missing metadata fields: {missing}")

    # 4. ID exists
    doc_id = meta.get("id", "")
    if not doc_id:
        report.errors.append(f"{name}: metadata has no id")
        return report

    # 5. DB record exists and path matches
    if is_wiki:
        _check_wiki_db_sync(doc_id, doc_dir, meta, report)
    else:
        _check_knowledge_db_sync(doc_id, doc_dir, meta, report)

    return report


def _relative_data_path(path: str) -> str:
    """Extract the relative path after 'data/' for path comparison.

    This avoids false mismatches between host (/root/.../data/knowledge/...)
    and container (/app/data/knowledge/...) paths.
    """
    for marker in ("/data/knowledge/", "/data/wiki/", "/data/raw/", "/data/workspace/"):
        idx = path.find(marker)
        if idx >= 0:
            return path[idx:]
    return path


def _check_knowledge_db_sync(
    doc_id: str, doc_dir: Path, meta: dict, report: IntegrityReport
) -> None:
    """Check knowledge doc DB sync."""
    db_doc = db.get_document(doc_id)
    if db_doc is None:
        report.warnings.append(f"{doc_dir.name}: exists on disk but not in DB (id={doc_id[:8]})")
        return

    db_path = db_doc.get("current_path", "")
    actual_path = str(doc_dir)
    # Compare relative paths to avoid host/container prefix mismatch
    if db_path and _relative_data_path(db_path) != _relative_data_path(actual_path):
        db.update_document(doc_id, current_path=actual_path)
        report.auto_fixed.append(
            f"{doc_dir.name}: DB path updated ({db_path} → {actual_path})"
        )


def _check_wiki_db_sync(
    doc_id: str, doc_dir: Path, meta: dict, report: IntegrityReport
) -> None:
    """Check wiki article DB sync."""
    conn = db.get_connection()
    row = conn.execute(
        "SELECT id, file_path FROM wiki_articles WHERE id = ?", (doc_id,)
    ).fetchone()
    conn.close()

    if row is None:
        report.warnings.append(
            f"{doc_dir.name}: wiki article on disk but not in DB (id={doc_id[:8]})"
        )
        return

    db_path = row["file_path"]
    actual_path = str(doc_dir)
    # Compare relative paths to avoid host/container prefix mismatch
    if db_path and _relative_data_path(db_path) != _relative_data_path(actual_path):
        db.update_wiki_article(doc_id, file_path=actual_path)
        report.auto_fixed.append(
            f"{doc_dir.name}: DB file_path updated ({db_path} → {actual_path})"
        )


# ── Full scan ──

def full_integrity_check() -> IntegrityReport:
    """Run a full integrity scan across knowledge/ and wiki/ vs database."""
    db.init_db()
    report = IntegrityReport()

    # Scan filesystem → check each folder
    fs_knowledge_ids = set()
    fs_wiki_ids = set()

    for root_dir, id_set, label in (
        (KNOWLEDGE_DIR, fs_knowledge_ids, "knowledge"),
        (WIKI_DIR, fs_wiki_ids, "wiki"),
    ):
        if not root_dir.exists():
            continue
        for meta_path in root_dir.rglob("metadata.json"):
            doc_dir = meta_path.parent
            # Skip INDEX.md level etc
            if not (doc_dir / "document.md").exists() and not meta_path.parent.name.startswith("."):
                # metadata.json without document.md
                pass

            sub_report = check_document(doc_dir)
            report.errors.extend(sub_report.errors)
            report.warnings.extend(sub_report.warnings)
            report.auto_fixed.extend(sub_report.auto_fixed)

            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                doc_id = meta.get("id", "")
                if doc_id:
                    id_set.add(doc_id)
            except Exception:
                pass

    # Check DB → filesystem: documents in DB but missing on disk
    conn = db.get_connection()

    # Knowledge documents
    db_docs = conn.execute("SELECT id, title, current_path FROM documents").fetchall()
    for row in db_docs:
        doc_id = row["id"]
        if doc_id not in fs_knowledge_ids:
            path = row["current_path"]
            if path and Path(path).exists():
                # Path exists but we didn't find metadata — odd
                report.warnings.append(
                    f"DB doc '{row['title']}' ({doc_id[:8]}): path exists but metadata not found"
                )
            else:
                report.errors.append(
                    f"DB doc '{row['title']}' ({doc_id[:8]}): file missing at {path}"
                )

    # Wiki articles
    db_wikis = conn.execute("SELECT id, title, file_path FROM wiki_articles").fetchall()
    for row in db_wikis:
        article_id = row["id"]
        if article_id not in fs_wiki_ids:
            path = row["file_path"]
            if path and Path(path).exists():
                report.warnings.append(
                    f"DB wiki '{row['title']}' ({article_id[:8]}): path exists but metadata not found"
                )
            else:
                report.errors.append(
                    f"DB wiki '{row['title']}' ({article_id[:8]}): file missing at {path}"
                )

    conn.close()

    all_ids = fs_knowledge_ids | fs_wiki_ids

    # Reference integrity (detection only — warnings)
    _check_reference_integrity(all_ids, report)

    # ── Deterministic auto-fixes ──
    fix_ghost_references(all_ids, report)
    fix_orphan_connection_backlinks(all_ids, report)
    fix_db_orphans(fs_knowledge_ids, fs_wiki_ids, report)

    logger.info("Integrity check: %s", report.summary())
    return report


def _check_reference_integrity(all_ids: set[str], report: IntegrityReport) -> None:
    """Check that all wiki references point to existing documents."""
    if not WIKI_DIR.exists():
        return

    for meta_path in WIKI_DIR.rglob("metadata.json"):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        title = meta.get("title", meta_path.parent.name)

        for src_id in meta.get("source_document_ids", []):
            if src_id and src_id not in all_ids:
                report.warnings.append(
                    f"'{title}': source_doc_id {src_id[:8]} not found"
                )

        for ref in meta.get("references", []):
            target = ref.get("target_id", "")
            if target and target not in all_ids:
                report.warnings.append(
                    f"'{title}': reference target {target[:8]} not found"
                )


# ── Deterministic auto-fix functions ──


def fix_ghost_references(all_ids: set[str], report: IntegrityReport) -> None:
    """Remove references to non-existent documents from wiki metadata.

    Fixes both source_document_ids and references[].target_id entries
    that point to IDs not found on disk.
    """
    if not WIKI_DIR.exists():
        return

    for meta_path in WIKI_DIR.rglob("metadata.json"):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        title = meta.get("title", meta_path.parent.name)
        article_id = meta.get("id", "")
        changed = False

        # Fix source_document_ids
        old_sources = meta.get("source_document_ids", [])
        new_sources = [sid for sid in old_sources if sid in all_ids]
        if len(new_sources) < len(old_sources):
            ghost_count = len(old_sources) - len(new_sources)
            meta["source_document_ids"] = new_sources
            changed = True
            report.auto_fixed.append(
                f"'{title}': removed {ghost_count} ghost source_doc_id(s)"
            )

        # Fix references
        old_refs = meta.get("references", [])
        new_refs = []
        dropped = 0
        for ref in old_refs:
            if not isinstance(ref, dict):
                dropped += 1
                continue
            target = ref.get("target_id", "")
            if target and target not in all_ids:
                dropped += 1
                continue
            new_refs.append(ref)

        if dropped > 0:
            meta["references"] = new_refs
            changed = True
            report.auto_fixed.append(
                f"'{title}': removed {dropped} ghost reference(s)"
            )

        if changed:
            meta_path.write_text(
                json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            # Update DB source_document_ids if article has an ID
            if article_id:
                try:
                    db.update_wiki_article(
                        article_id,
                        source_document_ids=json.dumps(new_sources),
                    )
                except Exception as e:
                    logger.warning("Failed to update DB for %s: %s", article_id[:8], e)


def fix_orphan_connection_backlinks(all_ids: set[str], report: IntegrityReport) -> None:
    """Ensure connection articles are back-referenced by the concepts they link.

    For each connection article, check that every concept/doc it references
    has a reciprocal 'related_concept' reference back to the connection.
    If missing, add the backlink to the concept's metadata.json.
    """
    if not WIKI_DIR.exists():
        return

    # Build a map of article_id → meta_path for quick lookup
    id_to_meta: dict[str, Path] = {}
    for meta_path in WIKI_DIR.rglob("metadata.json"):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            aid = meta.get("id", "")
            if aid:
                id_to_meta[aid] = meta_path
        except Exception:
            continue

    # Also index knowledge docs
    if KNOWLEDGE_DIR.exists():
        for meta_path in KNOWLEDGE_DIR.rglob("metadata.json"):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                aid = meta.get("id", "")
                if aid:
                    id_to_meta[aid] = meta_path
            except Exception:
                continue

    # Find all connection articles
    connection_dir = WIKI_DIR / "connection"
    if not connection_dir.exists():
        return

    for meta_path in connection_dir.rglob("metadata.json"):
        try:
            conn_meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        conn_id = conn_meta.get("id", "")
        conn_title = conn_meta.get("title", meta_path.parent.name)
        if not conn_id or conn_meta.get("article_type") != "connection":
            continue

        # Get all targets this connection references
        referenced_ids = set()
        for ref in conn_meta.get("references", []):
            if isinstance(ref, dict):
                tid = ref.get("target_id", "")
                if tid and tid != conn_id:
                    referenced_ids.add(tid)
        for sid in conn_meta.get("source_document_ids", []):
            if sid and sid != conn_id:
                referenced_ids.add(sid)

        # Check each referenced doc has a backlink to this connection
        for target_id in referenced_ids:
            if target_id not in id_to_meta:
                continue

            target_meta_path = id_to_meta[target_id]
            try:
                target_meta = json.loads(target_meta_path.read_text(encoding="utf-8"))
            except Exception:
                continue

            # Check if backlink already exists
            existing_refs = target_meta.get("references", [])
            has_backlink = any(
                isinstance(r, dict)
                and r.get("target_id") == conn_id
                for r in existing_refs
            )

            if not has_backlink:
                # Add backlink
                existing_refs.append({
                    "target_id": conn_id,
                    "relation": "related_concept",
                    "confidence": 0.8,
                })
                target_meta["references"] = existing_refs
                target_meta_path.write_text(
                    json.dumps(target_meta, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                target_title = target_meta.get("title", target_meta_path.parent.name)
                report.auto_fixed.append(
                    f"'{target_title}': added backlink to connection '{conn_title}'"
                )


def fix_db_orphans(
    fs_knowledge_ids: set[str],
    fs_wiki_ids: set[str],
    report: IntegrityReport,
) -> None:
    """Register filesystem documents that are missing from the database.

    Scans knowledge/ and wiki/ for docs with valid metadata.json that
    have no corresponding DB record, and inserts them.
    """
    if KNOWLEDGE_DIR.exists():
        for meta_path in KNOWLEDGE_DIR.rglob("metadata.json"):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            doc_id = meta.get("id", "")
            if not doc_id:
                continue
            db_doc = db.get_document(doc_id)
            if db_doc is not None:
                continue
            # Insert into DB
            try:
                db.insert_document(
                    doc_id=doc_id,
                    source_type=meta.get("source_type", "text"),
                    original_filename=meta.get("original_filename", ""),
                    current_path=str(meta_path.parent),
                    ingested_at=meta.get("ingested_at", ""),
                    title=meta.get("title", ""),
                )
                # Update additional fields if available
                updates = {}
                if meta.get("category"):
                    updates["category"] = meta["category"]
                if meta.get("subcategory"):
                    updates["subcategory"] = meta["subcategory"]
                if meta.get("status"):
                    updates["status"] = meta["status"]
                if meta.get("tags"):
                    updates["tags"] = json.dumps(meta["tags"])
                if updates:
                    db.update_document(doc_id, **updates)
                report.auto_fixed.append(
                    f"'{meta.get('title', doc_id[:8])}': registered in DB from disk"
                )
            except Exception as e:
                logger.warning("Failed to register doc %s in DB: %s", doc_id[:8], e)

    if WIKI_DIR.exists():
        for meta_path in WIKI_DIR.rglob("metadata.json"):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            article_id = meta.get("id", "")
            if not article_id:
                continue
            conn = db.get_connection()
            row = conn.execute(
                "SELECT id FROM wiki_articles WHERE id = ?", (article_id,)
            ).fetchone()
            conn.close()
            if row is not None:
                continue
            # Insert into DB
            try:
                from src.ingest.metadata import now_iso
                with db.transaction() as conn:
                    conn.execute(
                        """INSERT INTO wiki_articles
                           (id, title, article_type, file_path, summary, source_document_ids, created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            article_id,
                            meta.get("title", ""),
                            meta.get("article_type", ""),
                            str(meta_path.parent),
                            meta.get("summary", "")[:150] if meta.get("summary") else "",
                            json.dumps(meta.get("source_document_ids", [])),
                            meta.get("created_at", now_iso()),
                            meta.get("updated_at", now_iso()),
                        ),
                    )
                report.auto_fixed.append(
                    f"'{meta.get('title', article_id[:8])}': wiki article registered in DB from disk"
                )
            except Exception as e:
                logger.warning("Failed to register wiki %s in DB: %s", article_id[:8], e)
