"""File organizer — scans raw/, classifies, moves to knowledge/."""

import json
from pathlib import Path

from src.governance.classifier import classify
from src.ingest.metadata import now_iso, read_metadata, update_metadata
from src.shared.config import KNOWLEDGE_DIR, RAW_DIR
from src.shared.logger import get_logger
from src.storage import db
from src.storage.files import move_directory, read_file

logger = get_logger("governance.organizer")

CONFIDENCE_THRESHOLD = 0.8


def scan_and_organize() -> list[str]:
    """
    Scan all document folders in raw/, classify each one,
    and move to knowledge/. Returns list of processed doc IDs.
    """
    entries = _list_raw_entries()
    if not entries:
        logger.info("No documents in raw/")
        return []

    processed = []
    for doc_dir in entries:
        doc_id = _process_entry(doc_dir)
        if doc_id:
            processed.append(doc_id)

    logger.info("Organized %d documents", len(processed))
    return processed


def _list_raw_entries() -> list[Path]:
    """
    List all document folders in raw/.
    Each entry must be a directory containing metadata.json.
    """
    if not RAW_DIR.exists():
        return []

    entries = []
    for item in sorted(RAW_DIR.iterdir()):
        if item.name.startswith("."):
            continue
        if item.is_dir() and (item / "metadata.json").exists():
            entries.append(item)

    return entries


def _process_entry(doc_dir: Path) -> str | None:
    """Process a single document folder: classify -> move -> update."""
    metadata = read_metadata(doc_dir)
    doc_id = metadata.get("id")
    if not doc_id:
        logger.warning("Folder missing id in metadata: %s", doc_dir)
        return None

    md_path = doc_dir / "document.md"
    if not md_path.exists():
        logger.warning("Folder missing document.md: %s", doc_dir)
        return None

    body = read_file(md_path)
    result = classify(body)

    if result.confidence >= CONFIDENCE_THRESHOLD:
        target_parent = _build_target_dir(result.category, result.subcategory)
        new_status = "classified"
    else:
        target_parent = KNOWLEDGE_DIR / "misc"
        new_status = "needs_review"

    target_path = target_parent / doc_dir.name
    move_directory(doc_dir, target_path)

    relative_location = str(target_path.relative_to(target_path.parents[2]))
    update_metadata(target_path, {
        "title": result.title,
        "description": result.description,
        "tags": result.tags,
        "category": result.category,
        "subcategory": result.subcategory,
        "status": new_status,
        "location": relative_location,
        "classified_at": now_iso(),
    })

    db.update_document(
        doc_id,
        title=result.title,
        description=result.description,
        current_path=str(target_path),
        status=new_status,
        category=result.category,
        subcategory=result.subcategory,
        tags=json.dumps(result.tags, ensure_ascii=False),
        classified_at=now_iso(),
    )
    db.log_operation(
        doc_id,
        operation="classify",
        from_path=str(doc_dir),
        to_path=str(target_path),
        details_json=json.dumps({
            "confidence": result.confidence,
            "reasoning": result.reasoning,
        }, ensure_ascii=False),
    )

    logger.info(
        "Organized: %s -> %s (confidence=%.2f, status=%s)",
        doc_dir.name, relative_location, result.confidence, new_status,
    )
    return doc_id


def _build_target_dir(category: str, subcategory: str) -> Path:
    """Build target directory path under knowledge/."""
    target = KNOWLEDGE_DIR / category
    if subcategory:
        target = target / subcategory
    return target
