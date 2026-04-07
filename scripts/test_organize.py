"""Quick test: classify and organize documents from raw/ to knowledge/."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.governance.organizer import scan_and_organize
from src.shared.config import KNOWLEDGE_DIR
from src.storage.db import get_connection, init_db

if __name__ == "__main__":
    init_db()

    print("Scanning raw/ and organizing...")
    processed = scan_and_organize()

    if not processed:
        print("No documents to process.")
        sys.exit(0)

    print(f"\nProcessed {len(processed)} document(s).")

    conn = get_connection()
    for doc_id in processed:
        row = conn.execute("SELECT id, title, status, category, subcategory, current_path FROM documents WHERE id = ?", (doc_id,)).fetchone()
        print(f"\n=== Document: {row['title']} ===")
        print(f"  ID:          {row['id'][:8]}...")
        print(f"  Status:      {row['status']}")
        print(f"  Category:    {row['category']}/{row['subcategory']}")
        print(f"  Path:        {row['current_path']}")

        # Check metadata.json in new location
        doc_dir = Path(row["current_path"])
        meta_path = doc_dir / "metadata.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text())
            print(f"  Location:    {meta['location']}")
            print(f"  Tags:        {meta['tags']}")
            print(f"  Description: {meta['description'][:100]}...")

        # Check operations log
        ops = conn.execute(
            "SELECT operation, from_path, to_path FROM operations_log WHERE document_id = ? ORDER BY created_at",
            (doc_id,),
        ).fetchall()
        print(f"  Operations:  {len(ops)}")
        for op in ops:
            print(f"    {op['operation']}: {Path(op['from_path']).name if op['from_path'] else ''} -> {Path(op['to_path']).name}")

    conn.close()

    # Show knowledge/ structure
    print(f"\n=== knowledge/ structure ===")
    for item in sorted(KNOWLEDGE_DIR.rglob("*")):
        if item.name.startswith("."):
            continue
        rel = item.relative_to(KNOWLEDGE_DIR)
        indent = "  " * len(rel.parts)
        print(f"{indent}{item.name}{'/' if item.is_dir() else ''}")
