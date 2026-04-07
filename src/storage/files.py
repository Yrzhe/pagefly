"""文件系统操作 — 只暴露安全操作，禁止删除。"""

import shutil
from pathlib import Path

import yaml

from src.shared.logger import get_logger

logger = get_logger("storage.files")


def create_file(path: Path, content: str) -> None:
    """创建文件，自动创建父目录。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    logger.info("Created file: %s", path)


def read_file(path: Path) -> str:
    """读取文件内容。"""
    return path.read_text(encoding="utf-8")


def move_file(src: Path, dst: Path) -> None:
    """移动文件，自动创建目标目录。"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    logger.info("Moved file: %s -> %s", src, dst)


def list_files(directory: Path, pattern: str = "*.md") -> list[Path]:
    """列出目录下匹配模式的文件。"""
    if not directory.exists():
        return []
    return sorted(directory.rglob(pattern))


def parse_frontmatter(content: str) -> tuple[dict, str]:
    """解析 Markdown 文件的 YAML frontmatter 和正文。"""
    if not content.startswith("---"):
        return {}, content

    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, content

    metadata = yaml.safe_load(parts[1]) or {}
    body = parts[2].lstrip("\n")
    return metadata, body


def update_frontmatter(content: str, updates: dict) -> str:
    """更新 Markdown 文件的 frontmatter 字段，保留正文不变。"""
    metadata, body = parse_frontmatter(content)
    metadata.update(updates)
    new_frontmatter = yaml.dump(metadata, allow_unicode=True, default_flow_style=False)
    return f"---\n{new_frontmatter}---\n\n{body}"


def update_file_metadata(path: Path, updates: dict) -> None:
    """原地更新文件的 frontmatter 字段。"""
    content = read_file(path)
    updated = update_frontmatter(content, updates)
    path.write_text(updated, encoding="utf-8")
    logger.info("Updated metadata for: %s (fields: %s)", path, list(updates.keys()))
