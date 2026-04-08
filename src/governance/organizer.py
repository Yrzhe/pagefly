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

    source_type = metadata.get("source_type", "")

    # Voice memos go directly to memo/voice/ — skip LLM classifier
    if source_type == "voice":
        return _process_voice_memo(doc_dir, doc_id, metadata, md_path)

    body = read_file(md_path)
    result = classify(body)

    if result.confidence >= CONFIDENCE_THRESHOLD:
        target_parent = _build_target_dir(result.category, result.subcategory)
        new_status = "classified"
    else:
        target_parent = KNOWLEDGE_DIR / "misc"
        new_status = "needs_review"

    target_path = target_parent / doc_dir.name

    # Atomic-ish organize: move → update metadata → update DB
    # Rollback: move back to original location on failure
    relative_location = str(target_path)
    try:
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
            "relevance_score": result.relevance_score,
            "temporal_type": result.temporal_type,
            "key_claims": result.key_claims,
        })

        classified_ts = now_iso()
        with db.transaction() as conn:
            fields = {
                "title": result.title, "description": result.description,
                "current_path": str(target_path), "status": new_status,
                "category": result.category, "subcategory": result.subcategory,
                "tags": json.dumps(result.tags, ensure_ascii=False),
                "classified_at": classified_ts,
            }
            set_clause = ", ".join(f"{k} = ?" for k in fields)
            conn.execute(
                f"UPDATE documents SET {set_clause} WHERE id = ?",
                [*fields.values(), doc_id],
            )
            conn.execute(
                """INSERT INTO operations_log (document_id, operation, from_path, to_path, details_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (doc_id, "classify", str(doc_dir), str(target_path),
                 json.dumps({"confidence": result.confidence, "reasoning": result.reasoning}, ensure_ascii=False),
                 classified_ts),
            )
    except Exception as e:
        # Rollback: move back to original location
        if target_path.exists() and not doc_dir.exists():
            try:
                move_directory(target_path, doc_dir)
                logger.warning("Rolled back move: %s → %s", target_path.name, doc_dir)
            except Exception:
                logger.error("Rollback also failed for %s", doc_id[:8])
        logger.error("Organize failed for %s: %s", doc_id[:8], e)
        return None

    # Activity log
    from src.shared.activity_log import append_log
    claims_str = "; ".join(result.key_claims[:3]) if result.key_claims else "none"
    append_log(
        "classify",
        f"{result.title}",
        f"→ {relative_location} (confidence={result.confidence:.2f}, relevance={result.relevance_score}/10, {result.temporal_type})\nKey claims: {claims_str}",
    )

    logger.info(
        "Organized: %s -> %s (confidence=%.2f, status=%s)",
        doc_dir.name, relative_location, result.confidence, new_status,
    )
    return doc_id


def _process_voice_memo(doc_dir: Path, doc_id: str, metadata: dict, md_path: Path) -> str | None:
    """Route voice transcriptions directly to memo/voice/ without LLM classification."""
    title = metadata.get("title", doc_dir.name)
    target_parent = KNOWLEDGE_DIR / "memo" / "voice"
    target_path = target_parent / doc_dir.name

    try:
        move_directory(doc_dir, target_path)

        relative_location = str(target_path.relative_to(target_path.parents[3]))
        update_metadata(target_path, {
            "title": title,
            "description": "Voice memo transcription",
            "tags": ["voice-memo"],
            "category": "memo",
            "subcategory": "voice",
            "status": "classified",
            "location": relative_location,
            "classified_at": now_iso(),
        })

        classified_ts = now_iso()
        with db.transaction() as conn:
            fields = {
                "title": title, "description": "Voice memo transcription",
                "current_path": str(target_path), "status": "classified",
                "category": "memo", "subcategory": "voice",
                "tags": json.dumps(["voice-memo"], ensure_ascii=False),
                "classified_at": classified_ts,
            }
            set_clause = ", ".join(f"{k} = ?" for k in fields)
            conn.execute(
                f"UPDATE documents SET {set_clause} WHERE id = ?",
                [*fields.values(), doc_id],
            )
            conn.execute(
                """INSERT INTO operations_log (document_id, operation, from_path, to_path, details_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (doc_id, "classify", str(doc_dir), str(target_path),
                 json.dumps({"source_type": "voice", "auto_routed": True}, ensure_ascii=False),
                 classified_ts),
            )
    except Exception as e:
        if target_path.exists() and not doc_dir.exists():
            try:
                move_directory(target_path, doc_dir)
            except Exception:
                pass
        logger.error("Voice memo organize failed for %s: %s", doc_id[:8], e)
        return None

    from src.shared.activity_log import append_log
    append_log("classify", title, f"→ {relative_location} (voice memo, auto-routed)")
    logger.info("Voice memo organized: %s -> %s", doc_dir.name, relative_location)
    return doc_id


def _build_target_dir(category: str, subcategory: str) -> Path:
    """Build target directory path under knowledge/."""
    target = KNOWLEDGE_DIR / category
    if subcategory:
        target = target / subcategory
    return target
