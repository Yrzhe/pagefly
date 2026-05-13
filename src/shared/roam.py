"""Roam — random knowledge resurfacing with dedup and staleness weighting.

Selects from wiki concept/connection/insight articles (compiled, evergreen knowledge)
rather than raw documents (which may be time-sensitive news or chat logs).
Publishes a rendered HTML page via here.now (24h expiry) for readable viewing.
"""

import json
import random
from datetime import datetime, timezone
from pathlib import Path

import httpx

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


_ROAM_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Daily Roam — PageFly</title>
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;background:#FFFEF5;color:#1C1917;line-height:1.7}
.container{max-width:720px;margin:0 auto;padding:32px 24px 64px}
header{text-align:center;margin-bottom:40px;padding-bottom:24px;border-bottom:1px solid #E7E5E4}
header h1{font-family:'Space Grotesk',system-ui,sans-serif;font-size:24px;font-weight:700;color:#1C1917;margin-bottom:4px}
header .sub{font-size:13px;color:#A8A29E}
.article{margin-bottom:48px;padding-bottom:32px;border-bottom:1px solid #E7E5E4}
.article:last-child{border-bottom:none}
.article-header{margin-bottom:16px}
.article-header h2{font-family:'Space Grotesk',system-ui,sans-serif;font-size:20px;font-weight:700;color:#1C1917;margin-bottom:6px}
.badge{display:inline-block;font-size:11px;font-weight:700;padding:2px 8px;border-radius:4px;background:#FFF3D0;color:#D97706}
.content{font-size:15px;color:#44403C}
.content h1,.content h2,.content h3{font-family:'Space Grotesk',system-ui,sans-serif;color:#1C1917;margin:20px 0 8px}
.content h1{font-size:22px}.content h2{font-size:18px}.content h3{font-size:16px}
.content p{margin:8px 0}
.content ul,.content ol{margin:8px 0 8px 24px}
.content li{margin:4px 0}
.content code{font-family:'IBM Plex Mono',monospace;font-size:13px;background:#FDF6E3;padding:1px 5px;border-radius:3px}
.content pre{background:#FDF6E3;padding:12px 16px;border-radius:8px;overflow-x:auto;margin:12px 0}
.content pre code{background:none;padding:0}
.content blockquote{border-left:3px solid #F59E0B;padding:8px 16px;margin:12px 0;color:#78716C;background:#FEF9EF;border-radius:0 6px 6px 0}
.content table{border-collapse:collapse;width:100%;margin:12px 0;font-size:14px}
.content th,.content td{border:1px solid #E7E5E4;padding:8px 12px;text-align:left}
.content th{background:#FFF8E7;font-weight:600}
.content a{color:#2563EB;text-decoration:underline}
footer{text-align:center;font-size:12px;color:#A8A29E;margin-top:48px}
</style>
</head>
<body>
<div class="container">
<header>
<h1>Daily Roam</h1>
<p class="sub">ROAM_DATE — PageFly Knowledge Base</p>
</header>
ARTICLES_HTML
<footer>Published by PageFly · expires in 24 hours</footer>
</div>
<script>
document.querySelectorAll('.content').forEach(el => {
  el.innerHTML = marked.parse(el.getAttribute('data-md'));
});
</script>
</body>
</html>
"""


def _build_roam_html(items: list[dict]) -> str:
    """Build a self-contained HTML page for roam articles."""
    today = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")

    articles = []
    for i, item in enumerate(items, 1):
        article_type = item.get("preview_type", "")
        # Escape for HTML attribute (data-md)
        md_escaped = (item["preview"]
                      .replace("&", "&amp;")
                      .replace('"', "&quot;")
                      .replace("<", "&lt;")
                      .replace(">", "&gt;"))
        articles.append(
            f'<div class="article">\n'
            f'<div class="article-header">\n'
            f'<h2>{i}. {item["title"]}</h2>\n'
            f'<span class="badge">{article_type}</span>\n'
            f'</div>\n'
            f'<div class="content" data-md="{md_escaped}"></div>\n'
            f'</div>'
        )

    html = _ROAM_HTML_TEMPLATE.replace("ROAM_DATE", today)
    html = html.replace("ARTICLES_HTML", "\n".join(articles))
    return html


def publish_roam_page(items: list[dict]) -> str | None:
    """Publish roam articles to here.now as a rendered HTML page (24h expiry).

    Returns the public URL or None on failure.
    """
    if not items:
        return None

    html_content = _build_roam_html(items)
    html_bytes = html_content.encode("utf-8")

    try:
        # Step 1: Create site
        resp = httpx.post(
            "https://here.now/api/v1/publish",
            headers={
                "Content-Type": "application/json",
                "X-HereNow-Client": "pagefly/roam",
            },
            json={
                "files": [
                    {"path": "index.html", "size": len(html_bytes), "contentType": "text/html; charset=utf-8"}
                ]
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        site_url = data.get("siteUrl", "")
        upload = data.get("upload", {})
        uploads = upload.get("uploads", [])
        finalize_url = upload.get("finalizeUrl", "")
        version_id = upload.get("versionId", "")

        if not uploads or not finalize_url:
            logger.warning("here.now: missing uploads or finalizeUrl in response")
            return None

        # Step 2: Upload HTML
        upload_info = uploads[0]
        upload_url = upload_info.get("url", "")
        upload_headers = upload_info.get("headers", {})
        resp2 = httpx.put(
            upload_url,
            content=html_bytes,
            headers=upload_headers,
            timeout=15,
        )
        resp2.raise_for_status()

        # Step 3: Finalize
        resp3 = httpx.post(
            finalize_url,
            headers={"Content-Type": "application/json"},
            json={"versionId": version_id},
            timeout=15,
        )
        resp3.raise_for_status()

        logger.info("Roam page published: %s", site_url)
        return site_url

    except Exception as e:
        logger.warning("Failed to publish roam page: %s", e)
        return None
