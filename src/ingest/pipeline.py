"""Ingest pipeline — unified entry point, dispatches to converters."""

import re
from pathlib import Path

from src.ingest.converters import pdf as pdf_converter
from src.ingest.converters import text as text_converter
from src.ingest.metadata import build_metadata, write_metadata
from src.shared.config import RAW_DIR
from src.shared.logger import get_logger
from src.shared.types import ConvertResult, IngestInput
from src.storage import db
from src.storage.files import create_file, write_bytes

logger = get_logger("ingest.pipeline")

# Register all converters (add a line here for new formats)
CONVERTERS = [
    pdf_converter,
    text_converter,
    # image_converter,
    # voice_converter,
    # docx_converter,
    # url_converter,
]


def ingest(input_data: IngestInput) -> str | None:
    """
    Run the ingest pipeline:
    1. Find a matching converter
    2. Convert to markdown
    3. Create document folder with metadata.json
    4. Write markdown + assets
    5. Record in database
    Returns document ID, or None on failure.
    """
    converter = _find_converter(input_data)
    if converter is None:
        logger.error("No converter found for input: %s", input_data)
        return None

    result = converter.convert(input_data)
    logger.info("Converted: %s -> markdown (%d chars)", input_data.original_filename, len(result.markdown))

    source_type = _detect_source_type(input_data)
    metadata = build_metadata(source_type, input_data.original_filename)
    doc_id = metadata["id"]

    folder_name = _build_folder_name(result.title, doc_id)
    metadata["title"] = result.title
    doc_dir = RAW_DIR / folder_name
    _write_document(doc_dir, result, metadata)

    db.insert_document(
        doc_id=doc_id,
        title=result.title,
        source_type=source_type,
        original_filename=input_data.original_filename,
        current_path=str(doc_dir),
        ingested_at=metadata["ingested_at"],
    )
    db.log_operation(doc_id, "ingest", to_path=str(doc_dir))

    logger.info("Ingested document: %s (id=%s)", doc_dir.name, doc_id[:8])
    return doc_id


def _write_document(doc_dir: Path, result: ConvertResult, metadata: dict) -> None:
    """
    Write document folder to raw/:
      doc_dir/
        document.md
        metadata.json
        images/        (if any)
    """
    create_file(doc_dir / "document.md", result.markdown)
    write_metadata(doc_dir, metadata)

    for img in result.images:
        write_bytes(doc_dir / "images" / img.filename, img.data)


def _sanitize_title(title: str, max_len: int = 60) -> str:
    """Clean title for use as folder name."""
    cleaned = re.sub(r'[\\/:*?"<>|]', '', title)
    cleaned = cleaned.strip().replace(' ', '_')
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rstrip('_')
    return cleaned


def _build_folder_name(title: str, doc_id: str) -> str:
    """Build folder name: {sanitized_title}_{id_short} or untitled_{id_short}."""
    sanitized = _sanitize_title(title) if title else ""
    id_short = doc_id[:8]
    if sanitized:
        return f"{sanitized}_{id_short}"
    return f"untitled_{id_short}"


def _find_converter(input_data: IngestInput):
    """Find the first converter that can handle this input."""
    for conv in CONVERTERS:
        if conv.can_handle(input_data):
            return conv
    return None


def _detect_source_type(input_data: IngestInput) -> str:
    """Detect source_type from input."""
    if input_data.type == "text":
        return "text"
    if input_data.type == "url":
        return "url"
    if input_data.file_path:
        ext = Path(input_data.file_path).suffix.lower()
        type_map = {
            ".txt": "text", ".md": "text", ".markdown": "text",
            ".pdf": "pdf",
            ".jpg": "image", ".jpeg": "image", ".png": "image",
            ".mp3": "voice", ".wav": "voice", ".ogg": "voice", ".m4a": "voice",
            ".docx": "docx", ".doc": "docx",
        }
        return type_map.get(ext, "text")
    return "text"
