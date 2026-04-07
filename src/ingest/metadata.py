"""YAML frontmatter 注入和校验。"""

import uuid
from datetime import datetime, timezone

import yaml


def generate_id() -> str:
    """生成文档 UUID。"""
    return str(uuid.uuid4())


def now_iso() -> str:
    """当前时间 ISO 8601 带时区。"""
    return datetime.now(timezone.utc).astimezone().isoformat()


def validate_datetime(dt_str: str) -> bool:
    """校验时间格式是否为 ISO 8601。"""
    try:
        datetime.fromisoformat(dt_str)
        return True
    except (ValueError, TypeError):
        return False


def build_frontmatter(source_type: str, original_filename: str) -> dict:
    """构建初始 metadata 字典。"""
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
    }


def inject_metadata(markdown_content: str, source_type: str, original_filename: str) -> str:
    """在 Markdown 内容前插入 YAML frontmatter。"""
    metadata = build_frontmatter(source_type, original_filename)
    frontmatter = yaml.dump(metadata, allow_unicode=True, default_flow_style=False)
    return f"---\n{frontmatter}---\n\n{markdown_content}"


def validate_frontmatter(metadata: dict) -> list[str]:
    """校验 frontmatter 字段，返回错误列表。"""
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
