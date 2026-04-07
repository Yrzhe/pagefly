"""File system operations — only safe ops exposed, no delete."""

import shutil
from pathlib import Path

from src.shared.logger import get_logger

logger = get_logger("storage.files")


def create_file(path: Path, content: str) -> None:
    """Create a file, auto-creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    logger.info("Created file: %s", path)


def read_file(path: Path) -> str:
    """Read file content as text."""
    return path.read_text(encoding="utf-8")


def move_file(src: Path, dst: Path) -> None:
    """Move a file, auto-creating target directory."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    logger.info("Moved file: %s -> %s", src, dst)


def move_directory(src: Path, dst: Path) -> None:
    """Move an entire directory, auto-creating target parent."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    logger.info("Moved directory: %s -> %s", src, dst)


def write_bytes(path: Path, data: bytes) -> None:
    """Write binary data to a file, auto-creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    logger.info("Wrote bytes: %s (%d bytes)", path, len(data))


def list_files(directory: Path, pattern: str = "*.md") -> list[Path]:
    """List files matching a pattern recursively."""
    if not directory.exists():
        return []
    return sorted(directory.rglob(pattern))


