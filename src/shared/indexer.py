"""Wiki index generator — produces wiki/INDEX.md from database."""

import json
from collections import defaultdict
from pathlib import Path

from src.shared.config import WIKI_DIR, KNOWLEDGE_DIR
from src.shared.logger import get_logger
from src.storage import db

logger = get_logger("shared.indexer")

INDEX_PATH = WIKI_DIR / "INDEX.md"


def generate_wiki_index() -> Path:
    """
    Generate wiki/INDEX.md from database + filesystem.

    The INDEX.md is a compact, LLM-readable overview of the entire wiki.
    It is always regenerated from DB — never manually edited.

    Returns the path to the generated INDEX.md.
    """
    db.init_db()

    # Gather wiki articles from DB
    articles = db.list_wiki_articles_db()

    # Gather knowledge doc stats
    knowledge_count = 0
    category_counts: dict[str, int] = defaultdict(int)
    if KNOWLEDGE_DIR.exists():
        for meta_path in KNOWLEDGE_DIR.rglob("metadata.json"):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                knowledge_count += 1
                cat = meta.get("category", "misc")
                category_counts[cat] += 1
            except Exception:
                pass

    # Group articles by type
    by_type: dict[str, list[dict]] = defaultdict(list)
    for article in articles:
        by_type[article["article_type"]].append(article)

    # Build markdown
    lines = [
        "# PageFly Wiki Index",
        "",
        f"> Auto-generated from database. {len(articles)} wiki articles, "
        f"{knowledge_count} knowledge documents.",
        f"> Last updated: {db.now_iso()}",
        "",
    ]

    # Knowledge overview section
    if category_counts:
        lines.append("## Knowledge Base Overview")
        lines.append("")
        for cat, count in sorted(category_counts.items(), key=lambda x: -x[1]):
            lines.append(f"- **{cat}**: {count} docs")
        lines.append("")

    # Wiki articles by type
    type_labels = {
        "summary": "Summaries",
        "concept": "Concepts",
        "connection": "Connections",
        "insight": "Insights",
        "qa": "Q&A",
        "lint": "Lint Reports",
    }

    for article_type in ("summary", "concept", "connection", "insight", "qa", "lint"):
        type_articles = by_type.get(article_type, [])
        if not type_articles:
            continue

        label = type_labels.get(article_type, article_type.title())
        lines.append(f"## {label} ({len(type_articles)})")
        lines.append("")

        for article in sorted(type_articles, key=lambda a: a["title"]):
            title = article["title"]
            summary = article.get("summary") or ""
            file_path = article.get("file_path", "")

            # Build relative path from wiki/ root
            try:
                rel = Path(file_path).relative_to(WIKI_DIR)
                link = str(rel / "document.md")
            except (ValueError, TypeError):
                link = file_path

            line = f"- [{title}]({link})"
            if summary:
                line += f" — {summary}"
            lines.append(line)

        lines.append("")

    # Write INDEX.md
    WIKI_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text("\n".join(lines), encoding="utf-8")

    logger.info(
        "Wiki index generated: %d articles, %d knowledge docs",
        len(articles),
        knowledge_count,
    )
    return INDEX_PATH
