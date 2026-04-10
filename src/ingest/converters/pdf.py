"""PDF converter — uses Mistral OCR to extract text and images."""

import base64
import time
from pathlib import Path

from mistralai.client import Mistral
from mistralai.client.models.documenturlchunk import DocumentURLChunk

from src.shared.config import MISTRAL_API_KEY, MISTRAL_BASE_URL
from src.shared.logger import get_logger
from src.shared.types import ConvertResult, ImageAsset, IngestInput

logger = get_logger("ingest.converters.pdf")

MAX_RETRIES = 3
RETRY_BACKOFF = 2  # exponential backoff base (seconds)


def _get_client() -> Mistral:
    """Create Mistral client (lazy initialization)."""
    return Mistral(api_key=MISTRAL_API_KEY, server_url=MISTRAL_BASE_URL)


def can_handle(input_data: IngestInput) -> bool:
    """Check if this converter can handle the input."""
    if input_data.type == "file" and input_data.file_path:
        p = Path(input_data.file_path)
        return p.exists() and p.suffix.lower() == ".pdf"
    return False


def convert(input_data: IngestInput) -> ConvertResult:
    """
    PDF -> Markdown + image assets.
    Flow: upload -> OCR -> extract images -> describe images -> assemble markdown.
    Each step has retry (3x exponential backoff). If OCR fully fails,
    returns a minimal document with error note rather than crashing.
    """
    pdf_path = Path(input_data.file_path)
    pdf_name = pdf_path.stem
    client = _get_client()

    try:
        ocr_response = _run_ocr(client, pdf_path)
    except Exception as e:
        logger.warning("Mistral OCR failed for %s, trying image-based fallback: %s", pdf_name, e)
        try:
            ocr_response = _run_ocr_image_fallback(client, pdf_path)
        except Exception as e2:
            logger.error("PDF OCR completely failed for %s: %s", pdf_name, e2)
            return ConvertResult(
                markdown=(
                    f"# {pdf_name}\n\n"
                    f"> OCR failed after all attempts: {e2}\n\n"
                    f"Original file: {input_data.original_filename or pdf_name}"
                ),
                title=pdf_name,
                images=[],
                has_error=True,
            )

    images = _extract_images(ocr_response, pdf_name)
    markdown = _build_markdown(ocr_response, images)
    title = _extract_title(markdown, input_data.original_filename or pdf_name)

    described_images = _describe_all_images(client, images)
    markdown = _append_image_descriptions(markdown, described_images)

    logger.info(
        "PDF converted: %s (%d pages, %d images)",
        pdf_name, len(ocr_response.pages), len(described_images),
    )
    return ConvertResult(
        markdown=markdown,
        title=title,
        images=described_images,
    )


def _run_ocr(client: Mistral, pdf_path: Path):
    """Upload PDF and run OCR with retry."""
    pdf_bytes = pdf_path.read_bytes()

    uploaded_file = _retry(
        lambda: client.files.upload(
            file={"file_name": pdf_path.name, "content": pdf_bytes},
            purpose="ocr",
        ),
        action="upload PDF",
    )

    signed_url = _retry(
        lambda: client.files.get_signed_url(file_id=uploaded_file.id, expiry=1),
        action="get signed URL",
    )

    ocr_response = _retry(
        lambda: client.ocr.process(
            document=DocumentURLChunk(document_url=signed_url.url),
            model="mistral-ocr-latest",
            include_image_base64=True,
        ),
        action="OCR process",
    )

    return ocr_response


def _run_ocr_image_fallback(client: Mistral, pdf_path: Path):
    """Fallback: render pages as images, split into batches, OCR each batch."""
    import fitz  # pymupdf
    import tempfile
    from dataclasses import dataclass

    logger.info("Converting PDF pages to images for OCR fallback: %s", pdf_path.name)
    doc = fitz.open(str(pdf_path))
    page_count = len(doc)

    BATCH_SIZE = 10
    DPI = 150

    # Collect all OCR results
    all_pages = []

    for batch_start in range(0, page_count, BATCH_SIZE):
        batch_end = min(batch_start + BATCH_SIZE, page_count)
        logger.info("Processing pages %d-%d of %d", batch_start + 1, batch_end, page_count)

        # Build a small PDF from this batch
        batch_pdf = fitz.open()
        for page_num in range(batch_start, batch_end):
            page = doc[page_num]
            pix = page.get_pixmap(dpi=DPI)
            img_bytes = pix.tobytes("png")

            img_doc = fitz.open("png", img_bytes)
            rect = img_doc[0].rect
            new_page = batch_pdf.new_page(width=rect.width, height=rect.height)
            new_page.insert_image(rect, stream=img_bytes)
            img_doc.close()

        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        batch_pdf.save(tmp.name)
        batch_pdf.close()

        try:
            batch_result = _run_ocr(client, Path(tmp.name))
            all_pages.extend(batch_result.pages)
        except Exception as e:
            logger.warning("Batch %d-%d OCR failed: %s", batch_start + 1, batch_end, e)
        finally:
            Path(tmp.name).unlink(missing_ok=True)

    doc.close()

    if not all_pages:
        raise RuntimeError("All batches failed")

    # Build a combined response-like object
    @dataclass
    class CombinedResponse:
        pages: list

    logger.info("OCR fallback complete: %d pages processed", len(all_pages))
    return CombinedResponse(pages=all_pages)


def _extract_images(ocr_response, pdf_name: str) -> list[ImageAsset]:
    """Extract all images from OCR response."""
    images = []
    counter = 1

    for page in ocr_response.pages:
        for img in page.images:
            base64_str = img.image_base64
            if base64_str.startswith("data:"):
                base64_str = base64_str.split(",", 1)[1]

            image_bytes = base64.b64decode(base64_str)
            ext = Path(img.id).suffix if Path(img.id).suffix else ".png"
            filename = f"{pdf_name}_img_{counter:03d}{ext}"
            counter += 1

            images.append(ImageAsset(filename=filename, data=image_bytes))

    return images


def _build_markdown(ocr_response, images: list[ImageAsset]) -> str:
    """Assemble markdown, replacing image references with relative paths."""
    image_map: dict[str, str] = {}
    img_idx = 0

    for page in ocr_response.pages:
        for img in page.images:
            if img_idx < len(images):
                image_map[img.id] = images[img_idx].filename
                img_idx += 1

    pages_md = []
    for page in ocr_response.pages:
        md = page.markdown
        for img in page.images:
            if img.id in image_map:
                fname = image_map[img.id]
                md = md.replace(
                    f"![{img.id}]({img.id})",
                    f"![{fname}](./images/{fname})",
                )
        pages_md.append(md)

    return "\n\n".join(pages_md)


def _describe_all_images(client: Mistral, images: list[ImageAsset]) -> list[ImageAsset]:
    """Generate AI descriptions for all images."""
    described = []
    for img in images:
        description = _describe_image(client, img.data)
        described.append(ImageAsset(
            filename=img.filename,
            data=img.data,
            description=description,
        ))
    return described


def _describe_image(client: Mistral, image_bytes: bytes) -> str:
    """Describe a single image using Mistral vision model."""
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    data_url = f"data:image/png;base64,{b64}"

    try:
        response = _retry(
            lambda: client.chat.complete(
                model="mistral-small-latest",
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": data_url,
                        },
                        {
                            "type": "text",
                            "text": (
                                "Briefly describe this image in 1-3 sentences. "
                                "If it's a chart, explain the data trend. "
                                "If it's a diagram, explain the structure."
                            ),
                        },
                    ],
                }],
            ),
            action="describe image",
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.warning("Failed to describe image: %s", e)
        return ""


def _append_image_descriptions(markdown: str, images: list[ImageAsset]) -> str:
    """Append AI descriptions after each image reference in markdown."""
    for img in images:
        if not img.description:
            continue
        old = f"![{img.filename}](./images/{img.filename})"
        new = f"{old}\n\n> **Image description**: {img.description}"
        markdown = markdown.replace(old, new)
    return markdown


def _extract_title(markdown: str, fallback: str) -> str:
    """Extract title from first H1 heading."""
    for line in markdown.split("\n"):
        stripped = line.strip()
        if stripped.startswith("# ") and not stripped.startswith("##"):
            return stripped[2:].strip()
    return fallback


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
