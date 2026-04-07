"""Document metadata generation and validation."""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from src.shared.logger import get_logger

logger = get_logger("ingest.metadata")


def generate_id() -> str:
    """Generate a document UUID."""
    return str(uuid.uuid4())


def now_iso() -> str:
    """Current time in ISO 8601 with timezone."""
    return datetime.now(timezone.utc).astimezone().isoformat()


def validate_datetime(dt_str: str) -> bool:
    """Check if a string is valid ISO 8601."""
    try:
        datetime.fromisoformat(dt_str)
        return True
    except (ValueError, TypeError):
        return False


def build_metadata(source_type: str, original_filename: str) -> dict:
    """Build initial metadata dictionary for a new document."""
    return {
        "id": generate_id(),
        "title": "",
        "description": "",
        "source_type": source_type,
        "original_filename": original_filename,
        "ingested_at": now_iso(),
        "status": "raw",
        "location": "raw/",
        "tags": [],
        "category": "",
        "subcategory": "",
    }


def write_metadata(doc_dir: Path, metadata: dict) -> None:
    """Write metadata.json to a document folder."""
    path = doc_dir / "metadata.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("Wrote metadata: %s", path)


def read_metadata(doc_dir: Path) -> dict:
    """Read metadata.json from a document folder."""
    path = doc_dir / "metadata.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def update_metadata(doc_dir: Path, updates: dict) -> dict:
    """Update fields in metadata.json and return the updated metadata."""
    metadata = read_metadata(doc_dir)
    metadata.update(updates)
    write_metadata(doc_dir, metadata)
    return metadata


def validate_metadata(metadata: dict) -> list[str]:
    """Validate metadata fields, return list of errors."""
    errors = []

    required_fields = ["id", "source_type", "ingested_at", "status", "location"]
    for field in required_fields:
        if field not in metadata or not metadata[field]:
            errors.append(f"Missing required field: {field}")

    if "ingested_at" in metadata and metadata["ingested_at"]:
        if not validate_datetime(metadata["ingested_at"]):
            errors.append(f"Invalid datetime format for ingested_at: {metadata['ingested_at']}")

    if "classified_at" in metadata and metadata["classified_at"]:
        if not validate_datetime(metadata["classified_at"]):
            errors.append(f"Invalid datetime format for classified_at: {metadata['classified_at']}")

    valid_statuses = {"raw", "classified", "needs_review", "reviewed"}
    if metadata.get("status") and metadata["status"] not in valid_statuses:
        errors.append(f"Invalid status: {metadata['status']}")

    return errors
