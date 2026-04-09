"""Shared security helpers for path and filename validation."""

import re
from pathlib import Path


_SAFE_FILENAME_RE = re.compile(r"[^\w\-.]")


def resolve_under_base(base_dir: Path, raw_path: str | Path) -> Path:
    """Resolve a path and ensure it stays under the provided base directory."""
    base = base_dir.resolve()
    resolved = Path(raw_path).resolve()
    if not resolved.is_relative_to(base):
        raise ValueError(f"path escapes base directory: {base}")
    return resolved


def sanitize_filename(filename: str, default: str = "upload") -> str:
    """Strip path separators and unsafe characters from a user-controlled filename."""
    safe_name = _SAFE_FILENAME_RE.sub("_", Path(filename).name)
    return safe_name or default
