"""Roam — random knowledge resurfacing with dedup and staleness weighting."""

import json
from pathlib import Path

from src.shared.config import DATA_DIR
from src.shared.logger import get_logger
from src.storage import db

logger = get_logger("shared.roam")

# Known container data prefix — DB stores paths like /app/data/...
_CONTAINER_DATA = "/app/data/"


def _resolve_db_path(db_path: str) -> Path:
    """Translate a DB file_path to a local filesystem path.

    DB may store /app/data/... (container) while host has a different root.
    """
    if not db_path:
        return Path(db_path)
    if db_path.startswith(_CONTAINER_DATA):
        relative = db_path[len(_CONTAINER_DATA):]
        return DATA_DIR / relative
    return Path(db_path)


def _strip_frontmatter(raw: str) -> str:
    """Strip YAML frontmatter (handles double frontmatter from compiler bugs)."""
    while raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) >= 3:
            raw = parts[2].strip()
        else:
            break
    return raw


def _find_summary_for_doc(doc_id: str) -> str | None:
    """Find the wiki summary article for a knowledge document.

    Returns the summary content (frontmatter stripped) or None.
    """
    conn = db.get_connection()
    rows = conn.execute(
        "SELECT file_path FROM wiki_articles WHERE article_type = 'summary'"
    ).fetchall()
    conn.close()

    for row in rows:
        meta_path = _resolve_db_path(row["file_path"]) / "metadata.json"
        if not meta_path.exists():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if doc_id in meta.get("source_document_ids", []):
                md_path = _resolve_db_path(row["file_path"]) / "document.md"
                if md_path.exists():
                    raw = md_path.read_text(encoding="utf-8")
                    return _strip_frontmatter(raw)
        except Exception:
            continue
    return None


def _read_doc_preview(current_path: str, max_chars: int = 500) -> str:
    """Read raw document preview as fallback when no summary exists."""
    if not current_path:
        return ""
    md_path = _resolve_db_path(current_path) / "document.md"
    if not md_path.exists():
        return ""
    raw = md_path.read_text(encoding="utf-8")
    return _strip_frontmatter(raw)[:max_chars]


def pick_roam_docs(count: int = 3) -> list[dict]:
    """Pick random documents for roam, weighted by staleness, with dedup.

    Returns list of {id, title, category, subcategory, preview, ingested_at}.
    Recently roamed docs (last 14 days) are excluded.
    Older documents (by ingested_at) are more likely to be selected.
    """
    recently_roamed = db.get_recently_roamed(days=14)

    conn = db.get_connection()
    # Fetch candidates: all non-error docs older than 7 days
    rows = conn.execute(
        "SELECT id, title, category, subcategory, current_path, ingested_at "
        "FROM documents WHERE status != 'error'"
    ).fetchall()
    conn.close()

    # Filter out recently roamed
    candidates = [r for r in rows if r["id"] not in recently_roamed]

    # If too few after dedup, allow recently roamed ones (better than nothing)
    if len(candidates) < count:
        candidates = list(rows)

    if not candidates:
        return []

    # Weighted random: older docs get higher weight
    # Weight = days since ingested (min 1)
    import random
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    weighted = []
    for r in candidates:
        try:
            ingested = datetime.fromisoformat(r["ingested_at"].replace("Z", "+00:00"))
            age_days = max(1, (now - ingested).days)
        except Exception:
            age_days = 30  # default weight for unparseable dates
        weighted.append((r, age_days))

    # Weighted sample without replacement
    selected = []
    pool = list(weighted)
    for _ in range(min(count, len(pool))):
        total = sum(w for _, w in pool)
        if total <= 0:
            break
        pick = random.uniform(0, total)
        cumulative = 0
        for i, (r, w) in enumerate(pool):
            cumulative += w
            if cumulative >= pick:
                selected.append(r)
                pool.pop(i)
                break

    # Build results — prefer wiki summary, fallback to raw preview
    results = []
    for row in selected:
        summary = _find_summary_for_doc(row["id"])
        if summary:
            preview = summary
            preview_type = "summary"
        else:
            preview = _read_doc_preview(row["current_path"])
            preview_type = "raw"

        results.append({
            "id": row["id"],
            "title": row["title"] or "(untitled)",
            "category": row["category"] or "",
            "subcategory": row["subcategory"] or "",
            "preview": preview,
            "preview_type": preview_type,
            "ingested_at": row["ingested_at"] or "",
        })

    # Record roam
    db.record_roam([r["id"] for r in results])

    return results


def format_roam_message(items: list[dict], max_preview: int = 500) -> str:
    """Format roam items into a markdown message.

    Summary previews are shown in full (usually concise).
    Raw previews are truncated to max_preview chars.
    """
    if not items:
        return "No documents available for roam yet."

    lines = ["**Random Roam**\n"]
    for i, item in enumerate(items, 1):
        tag = item["category"]
        if item["subcategory"]:
            tag += f"/{item['subcategory']}"

        is_summary = item.get("preview_type") == "summary"
        preview = item["preview"]
        if not is_summary:
            preview = preview[:max_preview].replace("\n", " ")
            if len(item["preview"]) > max_preview:
                preview += "..."

        lines.append(f"**{i}. {item['title']}**")
        if tag:
            lines.append(f"   [{tag}]")
        if preview:
            lines.append(f"   {preview}")
        lines.append("")

    return "\n".join(lines)
