"""Roam — random knowledge resurfacing with dedup and staleness weighting."""

from pathlib import Path

from src.shared.logger import get_logger
from src.storage import db

logger = get_logger("shared.roam")


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

    # Build results with previews
    results = []
    for row in selected:
        preview = ""
        if row["current_path"]:
            md_path = Path(row["current_path"]) / "document.md"
            if md_path.exists():
                raw = md_path.read_text(encoding="utf-8")
                # Strip YAML frontmatter
                if raw.startswith("---"):
                    parts = raw.split("---", 2)
                    raw = parts[2].strip() if len(parts) >= 3 else raw
                preview = raw[:500]

        results.append({
            "id": row["id"],
            "title": row["title"] or "(untitled)",
            "category": row["category"] or "",
            "subcategory": row["subcategory"] or "",
            "preview": preview,
            "ingested_at": row["ingested_at"] or "",
        })

    # Record roam
    db.record_roam([r["id"] for r in results])

    return results


def format_roam_message(items: list[dict], max_preview: int = 200) -> str:
    """Format roam items into a markdown message."""
    if not items:
        return "No documents available for roam yet."

    lines = ["**Random Roam**\n"]
    for i, item in enumerate(items, 1):
        tag = item["category"]
        if item["subcategory"]:
            tag += f"/{item['subcategory']}"
        preview = item["preview"][:max_preview].replace("\n", " ")

        lines.append(f"**{i}. {item['title']}**")
        if tag:
            lines.append(f"   [{tag}]")
        if preview:
            lines.append(f"   {preview}...")
        lines.append("")

    return "\n".join(lines)
