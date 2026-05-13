"""Roam — random knowledge resurfacing with dedup and staleness weighting.

Selects from wiki concept/connection/insight articles (compiled, evergreen knowledge)
rather than raw documents (which may be time-sensitive news or chat logs).
"""

import json
import random
from datetime import datetime, timezone
from pathlib import Path

from src.shared.config import DATA_DIR
from src.shared.logger import get_logger
from src.storage import db

logger = get_logger("shared.roam")

# Known container data prefix — DB stores paths like /app/data/...
_CONTAINER_DATA = "/app/data/"

# Wiki article types worth resurfacing (evergreen knowledge)
_ROAM_ARTICLE_TYPES = ("concept", "connection", "insight")


def _resolve_db_path(db_path: str) -> Path:
    """Translate a DB file_path to a local filesystem path."""
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


def _read_article_content(file_path: str) -> str:
    """Read a wiki article's content, stripping frontmatter."""
    md_path = _resolve_db_path(file_path) / "document.md"
    if not md_path.exists():
        return ""
    raw = md_path.read_text(encoding="utf-8")
    return _strip_frontmatter(raw)


def pick_roam_docs(count: int = 3) -> list[dict]:
    """Pick random wiki articles for roam, weighted by staleness, with dedup.

    Selects from concept/connection/insight articles — these are compiled,
    evergreen knowledge. Excludes summary (1:1 doc mirror), review, lint.
    """
    recently_roamed = db.get_recently_roamed(days=14)

    conn = db.get_connection()
    placeholders = ",".join("?" for _ in _ROAM_ARTICLE_TYPES)
    rows = conn.execute(
        f"SELECT id, title, article_type, file_path, summary, created_at "
        f"FROM wiki_articles WHERE article_type IN ({placeholders})",
        _ROAM_ARTICLE_TYPES,
    ).fetchall()
    conn.close()

    # Filter out recently roamed
    candidates = [r for r in rows if r["id"] not in recently_roamed]

    # Fallback: if too few after dedup, allow recently roamed
    if len(candidates) < count:
        candidates = list(rows)

    if not candidates:
        return []

    # Weighted random: older articles get higher weight
    now = datetime.now(timezone.utc)
    weighted = []
    for r in candidates:
        try:
            created = datetime.fromisoformat(r["created_at"].replace("Z", "+00:00"))
            age_days = max(1, (now - created).days)
        except Exception:
            age_days = 30
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

    # Build results
    results = []
    for row in selected:
        content = _read_article_content(row["file_path"])

        results.append({
            "id": row["id"],
            "title": row["title"] or "(untitled)",
            "category": row["article_type"] or "",
            "subcategory": "",
            "preview": content,
            "preview_type": row["article_type"],
            "ingested_at": row["created_at"] or "",
        })

    # Record roam
    db.record_roam([r["id"] for r in results])

    return results


def format_roam_message(items: list[dict], max_preview: int = 800) -> str:
    """Format roam items into a markdown message.

    Each article preview is capped to avoid Telegram's 4096 char limit.
    """
    if not items:
        return "No articles available for roam yet."

    lines = ["**Random Roam**\n"]
    for i, item in enumerate(items, 1):
        article_type = item.get("preview_type", item.get("category", ""))
        preview = item["preview"][:max_preview].rstrip()
        if len(item["preview"]) > max_preview:
            preview += "\n\n_(full article in knowledge base)_"

        lines.append(f"**{i}. {item['title']}**")
        if article_type:
            lines.append(f"   [{article_type}]")
        if preview:
            lines.append(f"   {preview}")
        lines.append("")

    return "\n".join(lines)
