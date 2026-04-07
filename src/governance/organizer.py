"""文件整理 — 扫描 raw/，分类，移动到 knowledge/。"""

import json
from pathlib import Path

from src.governance.classifier import classify
from src.ingest.metadata import now_iso
from src.shared.config import KNOWLEDGE_DIR, RAW_DIR
from src.shared.logger import get_logger
from src.storage import db
from src.storage.files import list_files, move_file, parse_frontmatter, read_file, update_file_metadata

logger = get_logger("governance.organizer")

CONFIDENCE_THRESHOLD = 0.8


def scan_and_organize() -> list[str]:
    """
    扫描 raw/ 中的所有 .md 文件，逐个分类并移动到 knowledge/。
    返回处理的文档 ID 列表。
    """
    raw_files = list_files(RAW_DIR)
    if not raw_files:
        logger.info("No files in raw/")
        return []

    processed = []
    for file_path in raw_files:
        doc_id = _process_file(file_path)
        if doc_id:
            processed.append(doc_id)

    logger.info("Organized %d files", len(processed))
    return processed


def _process_file(file_path: Path) -> str | None:
    """处理单个文件：分类 -> 移动 -> 更新。"""
    content = read_file(file_path)
    metadata, body = parse_frontmatter(content)

    if not metadata.get("id"):
        logger.warning("File missing id in frontmatter: %s", file_path)
        return None

    doc_id = metadata["id"]
    result = classify(body)

    if result.confidence >= CONFIDENCE_THRESHOLD:
        target_dir = _build_target_dir(result.category, result.subcategory)
        new_status = "classified"
    else:
        target_dir = KNOWLEDGE_DIR / "misc"
        new_status = "needs_review"

    target_path = target_dir / file_path.name

    move_file(file_path, target_path)

    relative_location = str(target_path.relative_to(target_path.parents[2]))
    metadata_updates = {
        "title": result.title,
        "description": result.description,
        "tags": result.tags,
        "category": result.category,
        "subcategory": result.subcategory,
        "status": new_status,
        "location": relative_location,
        "classified_at": now_iso(),
    }
    update_file_metadata(target_path, metadata_updates)

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
        from_path=str(file_path),
        to_path=str(target_path),
        details_json=json.dumps({
            "confidence": result.confidence,
            "reasoning": result.reasoning,
        }, ensure_ascii=False),
    )

    logger.info(
        "Organized: %s -> %s (confidence=%.2f, status=%s)",
        file_path.name, relative_location, result.confidence, new_status,
    )
    return doc_id


def _build_target_dir(category: str, subcategory: str) -> Path:
    """构建目标目录路径。"""
    target = KNOWLEDGE_DIR / category
    if subcategory:
        target = target / subcategory
    return target
