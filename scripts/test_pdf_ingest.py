"""Quick test: ingest a PDF file through the pipeline."""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ingest.pipeline import ingest
from src.ingest.metadata import read_metadata
from src.shared.config import RAW_DIR
from src.shared.types import IngestInput
from src.storage.db import init_db

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/test_pdf_ingest.py <path-to-pdf>")
        sys.exit(1)

    pdf_path = Path(sys.argv[1]).resolve()
    if not pdf_path.exists():
        print(f"File not found: {pdf_path}")
        sys.exit(1)

    print(f"Initializing database...")
    init_db()

    print(f"Ingesting: {pdf_path}")
    input_data = IngestInput(
        type="file",
        file_path=str(pdf_path),
        original_filename=pdf_path.name,
    )

    doc_id = ingest(input_data)

    if doc_id:
        print(f"\nSuccess! Document ID: {doc_id}")

        # Find and display the created folder
        for item in sorted(RAW_DIR.iterdir()):
            if doc_id[:8] in item.name:
                print(f"Document folder: {item}")
                metadata = read_metadata(item)
                print(f"Metadata: {metadata}")

                md_path = item / "document.md"
                content = md_path.read_text(encoding="utf-8")
                preview = content[:500]
                print(f"\nMarkdown preview:\n{preview}...")

                images_dir = item / "images"
                if images_dir.exists():
                    imgs = list(images_dir.iterdir())
                    print(f"\nImages extracted: {len(imgs)}")
                    for img in imgs:
                        print(f"  - {img.name} ({img.stat().st_size} bytes)")
                break
    else:
        print("Ingest failed.")
