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
    if db_path and db_path != actual_path:
        # Auto-fix: update DB path
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
    if db_path and db_path != actual_path:
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

    # Reference integrity
    _check_reference_integrity(fs_knowledge_ids | fs_wiki_ids, report)

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
