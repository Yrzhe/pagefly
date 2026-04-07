"""Text/Markdown pass-through converter."""

from pathlib import Path

from src.shared.types import ConvertResult, IngestInput


def can_handle(input_data: IngestInput) -> bool:
    """Check if this converter can handle the input."""
    if input_data.type == "text" and input_data.text:
        return True
    if input_data.type == "file" and input_data.file_path:
        ext = Path(input_data.file_path).suffix.lower()
        return ext in {".txt", ".md", ".markdown"}
    return False


def convert(input_data: IngestInput) -> ConvertResult:
    """Convert to markdown — text types pass through directly."""
    if input_data.type == "text":
        markdown = input_data.text
    else:
        markdown = Path(input_data.file_path).read_text(encoding="utf-8")

    title = _extract_title(markdown, input_data.original_filename)

    return ConvertResult(markdown=markdown, title=title)


def _extract_title(markdown: str, filename: str) -> str:
    """Extract title from first H1, fallback to filename."""
    for line in markdown.split("\n"):
        stripped = line.strip()
        if stripped.startswith("# ") and not stripped.startswith("##"):
            return stripped[2:].strip()
    if filename:
        return Path(filename).stem
    return ""
