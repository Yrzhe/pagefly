"""Image converter — uses Mistral OCR + vision model for text extraction and description."""

import base64
import mimetypes
import time
from pathlib import Path

from mistralai.client import Mistral
from mistralai.client.models.documenturlchunk import DocumentURLChunk

from src.shared.config import MISTRAL_API_KEY, MISTRAL_BASE_URL
from src.shared.logger import get_logger
from src.shared.types import ConvertResult, ImageAsset, IngestInput

logger = get_logger("ingest.converters.image")

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".tif"}
MAX_RETRIES = 3
RETRY_BACKOFF = 2
OCR_MODEL = "mistral-ocr-latest"
VISION_MODEL = "mistral-small-latest"

DESCRIPTION_PROMPT = """\
Describe this image in 2-5 sentences: what it shows, the subject, context, and style.
If it contains a chart or diagram, describe the data and structure.
Output ONLY the description, no preamble.\
"""


def _get_client() -> Mistral:
    return Mistral(api_key=MISTRAL_API_KEY, server_url=MISTRAL_BASE_URL)


def can_handle(input_data: IngestInput) -> bool:
    if input_data.type == "file" and input_data.file_path:
        p = Path(input_data.file_path)
        return p.exists() and p.suffix.lower() in IMAGE_EXTENSIONS
    return False


def convert(input_data: IngestInput) -> ConvertResult:
    """Image -> Markdown (OCR + description) + original image as asset."""
    img_path = Path(input_data.file_path)
    img_name = img_path.stem
    ext = img_path.suffix.lower()
    client = _get_client()

    image_bytes = img_path.read_bytes()
    mime = mimetypes.guess_type(str(img_path))[0] or "image/png"

    # Step 1: OCR with mistral-ocr-latest (upload → signed URL → OCR)
    ocr_text = _run_ocr(client, img_path, image_bytes)

    # Step 2: Description with mistral-small-latest vision
    description = _describe_image(client, image_bytes, mime)

    # Build title
    title = _extract_title(ocr_text, description, input_data.original_filename or img_name)

    # Keep original image as asset
    asset_filename = f"{img_name}{ext}"
    image_asset = ImageAsset(
        filename=asset_filename,
        data=image_bytes,
        description=description,
    )

    # Assemble final markdown
    sections = [f"![{asset_filename}](./images/{asset_filename})", ""]

    if description:
        sections.append("## Description")
        sections.append("")
        sections.append(description)
        sections.append("")

    if ocr_text and ocr_text.strip():
        sections.append("## Extracted Content")
        sections.append("")
        sections.append(ocr_text)
    else:
        sections.append("## Extracted Content")
        sections.append("")
        sections.append("*No extractable text content.*")

    markdown = "\n".join(sections)

    logger.info(
        "Image converted: %s (ocr=%d chars, desc=%d chars)",
        img_name, len(ocr_text), len(description),
    )
    return ConvertResult(
        markdown=markdown,
        title=title,
        images=[image_asset],
    )


def _run_ocr(client: Mistral, img_path: Path, image_bytes: bytes) -> str:
    """Upload image and run OCR with mistral-ocr-latest."""
    try:
        uploaded_file = _retry(
            lambda: client.files.upload(
                file={"file_name": img_path.name, "content": image_bytes},
                purpose="ocr",
            ),
            action="upload image",
        )

        signed_url = _retry(
            lambda: client.files.get_signed_url(file_id=uploaded_file.id, expiry=1),
            action="get signed URL",
        )

        ocr_response = _retry(
            lambda: client.ocr.process(
                document=DocumentURLChunk(document_url=signed_url.url),
                model=OCR_MODEL,
            ),
            action="OCR process",
        )

        # Extract text from all pages
        texts = []
        for page in ocr_response.pages:
            if hasattr(page, "markdown") and page.markdown:
                texts.append(page.markdown)
        return "\n\n".join(texts)

    except Exception as e:
        logger.warning("OCR failed, falling back to vision-only: %s", e)
        return ""


def _describe_image(client: Mistral, image_bytes: bytes, mime: str) -> str:
    """Describe the image using mistral-small-latest vision model."""
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    data_url = f"data:{mime};base64,{b64}"

    response = _retry(
        lambda: client.chat.complete(
            model=VISION_MODEL,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": data_url},
                    {"type": "text", "text": DESCRIPTION_PROMPT},
                ],
            }],
        ),
        action="describe image",
    )
    return response.choices[0].message.content.strip()


def _extract_title(ocr_text: str, description: str, fallback: str) -> str:
    """Extract title from OCR headings, description, or filename."""
    # Try first heading from OCR
    for line in ocr_text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("# ") and not stripped.startswith("##"):
            return stripped[2:].strip()

    # Use filename as fallback
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
