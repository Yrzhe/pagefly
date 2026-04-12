"""Demo data loader — seeds the system with sample documents and wiki articles.

Usage:
    python -m src.demo load    # Copy demo data into data/ and register in DB
    python -m src.demo clear   # Remove demo documents and wiki articles
"""

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
DEMO_DIR = ROOT_DIR / "data" / "demo"
KNOWLEDGE_DIR = ROOT_DIR / "data" / "knowledge"
WIKI_DIR = ROOT_DIR / "data" / "wiki"


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def _read_metadata(doc_dir: Path) -> dict:
    with open(doc_dir / "metadata.json", encoding="utf-8") as f:
        return json.load(f)


def _iter_doc_dirs(root: Path):
    """Yield every directory that contains a metadata.json."""
    if not root.exists():
        return
    for metadata_path in root.rglob("metadata.json"):
        yield metadata_path.parent


def load() -> None:
    """Copy demo data into live data directory and register in DB."""
    if not DEMO_DIR.exists():
        print(f"  Demo directory not found: {DEMO_DIR}")
        sys.exit(1)

    from src.storage import db
    db.init_db()

    demo_knowledge = DEMO_DIR / "knowledge"
    demo_wiki = DEMO_DIR / "wiki"

    # Copy knowledge documents
    kn_count = 0
    for src_dir in _iter_doc_dirs(demo_knowledge):
        rel = src_dir.relative_to(demo_knowledge)
        dst_dir = KNOWLEDGE_DIR / rel
        if dst_dir.exists():
            print(f"  Skipping existing: {rel}")
            continue
        dst_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src_dir, dst_dir)
        meta = _read_metadata(dst_dir)

        with db.transaction() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO documents
                (id, title, description, source_type, original_filename, current_path,
                 status, tags, category, subcategory, ingested_at, classified_at, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    meta["id"],
                    meta.get("title", ""),
                    meta.get("description", ""),
                    meta.get("source_type", "text"),
                    meta.get("original_filename", ""),
                    str(dst_dir),
                    meta.get("status", "classified"),
                    json.dumps(meta.get("tags", [])),
                    meta.get("category", ""),
                    meta.get("subcategory", ""),
                    meta.get("ingested_at", _now_iso()),
                    meta.get("classified_at", ""),
                    json.dumps(meta),
                ),
            )
            conn.execute(
                """INSERT INTO operations_log (document_id, operation, from_path, to_path, details_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (meta["id"], "ingest", "", str(dst_dir), '{"demo": true}', meta.get("ingested_at", _now_iso())),
            )
            conn.execute(
                """INSERT INTO operations_log (document_id, operation, from_path, to_path, details_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (meta["id"], "classify", "", str(dst_dir), '{"demo": true}',
                 meta.get("classified_at") or meta.get("ingested_at", _now_iso())),
            )
        kn_count += 1
        print(f"  + Knowledge: {meta.get('title', rel)}")

    # Copy wiki articles
    wk_count = 0
    for src_dir in _iter_doc_dirs(demo_wiki):
        rel = src_dir.relative_to(demo_wiki)
        dst_dir = WIKI_DIR / rel
        if dst_dir.exists():
            print(f"  Skipping existing wiki: {rel}")
            continue
        dst_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src_dir, dst_dir)
        meta = _read_metadata(dst_dir)

        # Extract first few paragraphs as summary
        doc_path = dst_dir / "document.md"
        summary = ""
        if doc_path.exists():
            text = doc_path.read_text(encoding="utf-8")
            # Strip YAML frontmatter and heading, take first non-empty paragraph
            lines = text.split("\n")
            in_fm = False
            paras: list[str] = []
            current: list[str] = []
            for ln in lines:
                if ln.strip() == "---":
                    in_fm = not in_fm
                    continue
                if in_fm or ln.startswith("#"):
                    continue
                if not ln.strip():
                    if current:
                        paras.append(" ".join(current).strip())
                        current = []
                else:
                    current.append(ln.strip())
            if current:
                paras.append(" ".join(current).strip())
            summary = paras[0][:300] if paras else ""

        with db.transaction() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO wiki_articles
                (id, title, article_type, file_path, summary, source_document_ids, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    meta["id"],
                    meta["title"],
                    meta["article_type"],
                    str(dst_dir),
                    summary,
                    json.dumps(meta.get("source_documents", [])),
                    meta.get("created_at", _now_iso()),
                    meta.get("updated_at", _now_iso()),
                ),
            )
            # Log a wiki_compile operation against the first source document
            src_ids = meta.get("source_documents", [])
            if src_ids:
                conn.execute(
                    """INSERT INTO operations_log (document_id, operation, from_path, to_path, details_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    (src_ids[0], "wiki_compile", "", str(dst_dir), '{"demo": true}',
                     meta.get("created_at", _now_iso())),
                )
        wk_count += 1
        print(f"  + Wiki: {meta['title']}")

    print()
    print(f"  Loaded {kn_count} knowledge documents and {wk_count} wiki articles.")
    print(f"  Open the dashboard to explore them.")
    print()


def clear() -> None:
    """Remove demo documents and wiki articles from the system."""
    from src.storage import db
    db.init_db()

    demo_knowledge = DEMO_DIR / "knowledge"
    demo_wiki = DEMO_DIR / "wiki"
    removed = 0

    # Remove knowledge documents
    for src_dir in _iter_doc_dirs(demo_knowledge):
        meta = _read_metadata(src_dir)
        rel = src_dir.relative_to(demo_knowledge)
        dst_dir = KNOWLEDGE_DIR / rel
        if dst_dir.exists():
            shutil.rmtree(dst_dir)
        with db.transaction() as conn:
            conn.execute("DELETE FROM documents WHERE id = ?", (meta["id"],))
            conn.execute("DELETE FROM operations_log WHERE document_id = ?", (meta["id"],))
        removed += 1

    # Remove wiki articles
    for src_dir in _iter_doc_dirs(demo_wiki):
        meta = _read_metadata(src_dir)
        rel = src_dir.relative_to(demo_wiki)
        dst_dir = WIKI_DIR / rel
        if dst_dir.exists():
            shutil.rmtree(dst_dir)
        with db.transaction() as conn:
            conn.execute("DELETE FROM wiki_articles WHERE id = ?", (meta["id"],))
        removed += 1

    print(f"  Removed {removed} demo items.")


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] == "help":
        print()
        print("  PageFly Demo Loader")
        print()
        print("  Usage:")
        print("    python -m src.demo load    Copy demo documents & wiki into data/")
        print("    python -m src.demo clear   Remove demo data from data/ and DB")
        print()
        return

    cmd = args[0]
    if cmd == "load":
        load()
    elif cmd == "clear":
        clear()
    else:
        print(f"  Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
