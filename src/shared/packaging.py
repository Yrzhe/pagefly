"""File packaging utilities — ZIP and PDF generation."""

import shutil
import tempfile
from pathlib import Path

from src.shared.logger import get_logger

logger = get_logger("shared.packaging")


def zip_document(doc_dir: Path) -> Path:
    """
    Package a document folder into a ZIP file.
    Returns path to the temp ZIP file. Caller must clean up.
    """
    if not doc_dir.exists() or not doc_dir.is_dir():
        raise FileNotFoundError(f"Document folder not found: {doc_dir}")

    tmp_dir = Path(tempfile.mkdtemp())
    zip_name = doc_dir.name
    zip_path = tmp_dir / zip_name

    shutil.make_archive(str(zip_path), "zip", doc_dir)
    result = zip_path.with_suffix(".zip")

    logger.info("Created ZIP: %s (%d bytes)", result, result.stat().st_size)
    return result


def create_pdf_from_markdown(md_path: Path, title: str = "") -> Path:
    """
    Convert a markdown file to PDF with embedded images.
    Returns path to the temp PDF file. Caller must clean up.
    """
    try:
        import markdown
        from weasyprint import HTML
    except ImportError:
        raise RuntimeError(
            "PDF generation requires 'markdown' and 'weasyprint'. "
            "Install with: pip install markdown weasyprint"
        )

    content = md_path.read_text(encoding="utf-8")
    doc_dir = md_path.parent
    images_dir = doc_dir / "images"

    # Convert markdown to HTML
    html_body = markdown.markdown(content, extensions=["tables", "fenced_code"])

    # Fix image paths to absolute for PDF rendering
    if images_dir.exists():
        for img in images_dir.iterdir():
            html_body = html_body.replace(
                f"./images/{img.name}",
                f"file://{img.resolve()}",
            )

    html_template = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
body {{ font-family: sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; line-height: 1.6; }}
h1 {{ color: #333; border-bottom: 2px solid #eee; padding-bottom: 8px; }}
h2 {{ color: #555; }}
img {{ max-width: 100%; height: auto; }}
blockquote {{ border-left: 4px solid #ddd; margin: 0; padding: 0 16px; color: #666; }}
code {{ background: #f5f5f5; padding: 2px 6px; border-radius: 3px; }}
pre {{ background: #f5f5f5; padding: 16px; border-radius: 6px; overflow-x: auto; }}
</style>
</head>
<body>
{html_body}
</body>
</html>"""

    tmp_dir = Path(tempfile.mkdtemp())
    pdf_name = title or md_path.parent.name
    pdf_name = "".join(c for c in pdf_name if c not in r'\/:*?"<>|')[:60].strip()
    pdf_path = tmp_dir / f"{pdf_name}.pdf"

    HTML(string=html_template).write_pdf(str(pdf_path))

    logger.info("Created PDF: %s (%d bytes)", pdf_path, pdf_path.stat().st_size)
    return pdf_path


def cleanup_temp_file(file_path: Path) -> None:
    """Remove a temp file and its parent dir if empty."""
    try:
        file_path.unlink(missing_ok=True)
        parent = file_path.parent
        if parent.exists() and not any(parent.iterdir()):
            parent.rmdir()
        logger.info("Cleaned up: %s", file_path)
    except Exception as e:
        logger.warning("Failed to clean up %s: %s", file_path, e)
