"""Ingest Pipeline — 统一入口，调度到具体 converter。"""

from pathlib import Path

from src.ingest.converters import text as text_converter
from src.ingest.metadata import inject_metadata
from src.shared.config import RAW_DIR
from src.shared.logger import get_logger
from src.shared.types import IngestInput
from src.storage import db
from src.storage.files import create_file, parse_frontmatter

logger = get_logger("ingest.pipeline")

# 注册所有 converter（新增格式只需在这里加一行）
CONVERTERS = [
    text_converter,
    # pdf_converter,
    # image_converter,
    # voice_converter,
    # docx_converter,
    # url_converter,
]


def ingest(input_data: IngestInput) -> str | None:
    """
    执行入库流程：
    1. 找到能处理的 converter
    2. 转换为 Markdown
    3. 注入 metadata
    4. 写入 raw/
    5. 记录到数据库
    返回文档 ID，失败返回 None。
    """
    converter = _find_converter(input_data)
    if converter is None:
        logger.error("No converter found for input: %s", input_data)
        return None

    result = converter.convert(input_data)
    logger.info("Converted: %s -> markdown (%d chars)", input_data.original_filename, len(result.markdown))

    source_type = _detect_source_type(input_data)
    content_with_meta = inject_metadata(result.markdown, source_type, input_data.original_filename)

    metadata, _ = parse_frontmatter(content_with_meta)
    doc_id = metadata["id"]
    filename = f"{metadata['ingested_at'][:10]}_{doc_id[:8]}.md"
    file_path = RAW_DIR / filename

    create_file(file_path, content_with_meta)

    db.insert_document(
        doc_id=doc_id,
        source_type=source_type,
        original_filename=input_data.original_filename,
        current_path=str(file_path),
        ingested_at=metadata["ingested_at"],
    )
    db.log_operation(doc_id, "ingest", to_path=str(file_path))

    logger.info("Ingested document: %s (id=%s)", filename, doc_id[:8])
    return doc_id


def _find_converter(input_data: IngestInput):
    """遍历 converter，找到第一个能处理的。"""
    for conv in CONVERTERS:
        if conv.can_handle(input_data):
            return conv
    return None


def _detect_source_type(input_data: IngestInput) -> str:
    """根据输入推断 source_type。"""
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
