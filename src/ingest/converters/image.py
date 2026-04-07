"""Image converter — uses Mistral vision model for description and OCR."""

import base64
import mimetypes
import time
from pathlib import Path

from mistralai.client import Mistral

from src.shared.config import MISTRAL_API_KEY, MISTRAL_BASE_URL
from src.shared.logger import get_logger
from src.shared.types import ConvertResult, ImageAsset, IngestInput

logger = get_logger("ingest.converters.image")

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".tif"}
MAX_RETRIES = 3
RETRY_BACKOFF = 2
VISION_MODEL = "mistral-small-latest"

ANALYSIS_PROMPT = """\
Analyze this image and produce a Markdown document with TWO sections.

## Description
Write 2-5 sentences describing what this image shows: subject, context, style.

## Extracted Content
If the image contains readable text, tables, charts, diagrams, or structured data,
extract ALL of it faithfully below. Preserve the original structure:
- For text: reproduce it verbatim.
- For tables: use Markdown tables.
- For charts/diagrams: describe the data and structure in detail.
- For handwriting: transcribe as best as possible, noting uncertain parts with [?].

If the image contains NO readable text or structured data (e.g. a photo, artwork,
screenshot with no text), write: *No extractable text content.*

Output ONLY the Markdown, no preamble.\
"""


def _get_client() -> Mistral:
    return Mistral(api_key=MISTRAL_API_KEY, server_url=MISTRAL_BASE_URL)


def can_handle(input_data: IngestInput) -> bool:
    if input_data.type == "file" and input_data.file_path:
        return Path(input_data.file_path).suffix.lower() in IMAGE_EXTENSIONS
    return False


def convert(input_data: IngestInput) -> ConvertResult:
    """Image -> Markdown (description + OCR) + original image as asset."""
    img_path = Path(input_data.file_path)
    img_name = img_path.stem
    client = _get_client()

    image_bytes = img_path.read_bytes()
    mime = mimetypes.guess_type(str(img_path))[0] or "image/png"
    ext = img_path.suffix.lower()

    # Analyze image: description + OCR in one call
    markdown_body = _analyze_image(client, image_bytes, mime)

    # Build title from filename or first heading
    title = _extract_title(markdown_body, input_data.original_filename or img_name)

    # Keep original image as asset
    asset_filename = f"{img_name}{ext}"
    image_asset = ImageAsset(
        filename=asset_filename,
        data=image_bytes,
        description="",  # description is already in the markdown
    )

    # Assemble final markdown with image reference at the top
    markdown = (
        f"![{asset_filename}](./images/{asset_filename})\n\n"
        f"{markdown_body}"
    )

    logger.info("Image converted: %s (%d bytes)", img_name, len(image_bytes))
    return ConvertResult(
        markdown=markdown,
        title=title,
        images=[image_asset],
    )


def _analyze_image(client: Mistral, image_bytes: bytes, mime: str) -> str:
    """Run vision model to describe the image and extract any text/tables."""
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    data_url = f"data:{mime};base64,{b64}"

    response = _retry(
        lambda: client.chat.complete(
            model=VISION_MODEL,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": data_url},
                    {"type": "text", "text": ANALYSIS_PROMPT},
                ],
            }],
        ),
        action="analyze image",
    )
    return response.choices[0].message.content.strip()


def _extract_title(markdown: str, fallback: str) -> str:
    """Extract title from first H1/H2 heading, or use fallback."""
    for line in markdown.split("\n"):
        stripped = line.strip()
        if stripped.startswith("# ") and not stripped.startswith("##"):
            return stripped[2:].strip()
    # Image markdown typically starts with ## Description, use filename
    return Path(fallback).stem if "." in fallback else fallback


def _retry(fn, action: str = "operation", retries: int = MAX_RETRIES):
    """Retry with exponential backoff."""
    last_error = None
    for attempt in range(retries):
        try:
            return fn()
        except Exception as e:
            last_error = e
            wait = RETRY_BACKOFF ** attempt
            logger.warning(
                "%s failed (attempt %d/%d): %s. Retrying in %ds...",
                action, attempt + 1, retries, e, wait,
            )
            time.sleep(wait)
    raise RuntimeError(f"{action} failed after {retries} attempts: {last_error}") from last_error
