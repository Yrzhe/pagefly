"""Trend Discovery Agent — analyzes knowledge base growth patterns and emerging themes."""

import asyncio
from datetime import datetime, timedelta, timezone

from claude_agent_sdk import query

from src.agents.base import build_agent_options
from src.shared.config import load_skill_prompt
from src.shared.logger import get_logger
from src.storage.db import get_connection, init_db

logger = get_logger("agents.trend")


def _build_trend_context() -> str:
    """Pre-compute database statistics for the trend agent."""
    conn = get_connection()
    now = datetime.now(timezone.utc).astimezone()
    week_ago = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    two_weeks_ago = (now - timedelta(days=14)).strftime("%Y-%m-%d")
    month_ago = (now - timedelta(days=30)).strftime("%Y-%m-%d")

    sections = []

    # 1. Document counts
    total = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    this_week = conn.execute(
        "SELECT COUNT(*) FROM documents WHERE ingested_at >= ?", (week_ago,)
    ).fetchone()[0]
    last_week = conn.execute(
        "SELECT COUNT(*) FROM documents WHERE ingested_at >= ? AND ingested_at < ?",
        (two_weeks_ago, week_ago),
    ).fetchone()[0]
    this_month = conn.execute(
        "SELECT COUNT(*) FROM documents WHERE ingested_at >= ?", (month_ago,)
    ).fetchone()[0]

    sections.append(
        f"## Document Counts\n"
        f"- Total: {total}\n"
        f"- This week (since {week_ago}): {this_week}\n"
        f"- Last week: {last_week}\n"
        f"- This month (since {month_ago}): {this_month}"
    )

    # 2. Category distribution
    rows = conn.execute(
        "SELECT category, COUNT(*) as cnt FROM documents "
        "WHERE status != 'error' GROUP BY category ORDER BY cnt DESC"
    ).fetchall()
    cat_lines = [f"- {r['category'] or '(none)'}: {r['cnt']}" for r in rows]
    sections.append(f"## Category Distribution\n" + "\n".join(cat_lines))

    # 3. Recent docs by category (this week)
    rows = conn.execute(
        "SELECT category, COUNT(*) as cnt FROM documents "
        "WHERE ingested_at >= ? AND status != 'error' "
        "GROUP BY category ORDER BY cnt DESC",
        (week_ago,),
    ).fetchall()
    if rows:
        recent_lines = [f"- {r['category'] or '(none)'}: {r['cnt']}" for r in rows]
        sections.append(f"## This Week by Category\n" + "\n".join(recent_lines))

    # 4. Tag frequency (top 20)
    all_tags = conn.execute(
        "SELECT tags FROM documents WHERE tags != '[]' AND tags != '' AND tags IS NOT NULL"
    ).fetchall()
    tag_counts: dict[str, int] = {}
    import json
    for row in all_tags:
        try:
            tags = json.loads(row["tags"])
            for tag in tags:
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
        except Exception:
            pass

    top_tags = sorted(tag_counts.items(), key=lambda x: -x[1])[:20]
    if top_tags:
        tag_lines = [f"- {tag}: {count}" for tag, count in top_tags]
        sections.append(f"## Top Tags\n" + "\n".join(tag_lines))

    # 5. Wiki article counts by type
    rows = conn.execute(
        "SELECT article_type, COUNT(*) as cnt FROM wiki_articles "
        "GROUP BY article_type ORDER BY cnt DESC"
    ).fetchall()
    wiki_lines = [f"- {r['article_type']}: {r['cnt']}" for r in rows]
    wiki_total = sum(r["cnt"] for r in rows)
    sections.append(
        f"## Wiki Articles ({wiki_total} total)\n" + "\n".join(wiki_lines)
    )

    # 6. Recent operations
    rows = conn.execute(
        "SELECT operation, COUNT(*) as cnt FROM operations_log "
        "WHERE created_at >= ? GROUP BY operation ORDER BY cnt DESC",
        (week_ago,),
    ).fetchall()
    if rows:
        ops_lines = [f"- {r['operation']}: {r['cnt']}" for r in rows]
        sections.append(f"## Operations This Week\n" + "\n".join(ops_lines))

    # 7. Recent document titles (this week, for thematic analysis)
    rows = conn.execute(
        "SELECT title, category, subcategory FROM documents "
        "WHERE ingested_at >= ? AND status != 'error' "
        "ORDER BY ingested_at DESC LIMIT 30",
        (week_ago,),
    ).fetchall()
    if rows:
        doc_lines = [
            f"- [{r['category']}/{r['subcategory'] or '-'}] {r['title']}"
            for r in rows
        ]
        sections.append(
            f"## Recent Documents (this week, newest first)\n" + "\n".join(doc_lines)
        )

    conn.close()
    return "\n\n".join(sections)


async def run_trend() -> str:
    """
    Run the trend discovery agent.
    Pre-computes DB stats, then passes to LLM for analysis.
    Returns the trend analysis text.
    """
    init_db()

    # Load skill prompt
    try:
        skill_prompt = load_skill_prompt("trend", "SKILL")
    except FileNotFoundError:
        skill_prompt = "Analyze the knowledge base trends and produce an insight article."

    # Pre-compute stats
    logger.info("Computing trend statistics...")
    trend_context = _build_trend_context()

    prompt = (
        f"## Pre-Computed Trend Data\n\n"
        f"{trend_context}\n\n"
        f"---\n\n"
        f"Analyze the data above and produce a trend insight article. "
        f"Focus on what's changed, what's emerging, and what's worth exploring. "
        f"Write the article using write_wiki_article with article_type='insight'. "
        f"If relevant recent documents inform your analysis, include their IDs as source_doc_ids.\n\n"
        f"{skill_prompt}"
    )

    options = build_agent_options(skill_name="trend", max_turns=30)

    logger.info("Starting trend discovery agent...")
    response_parts = []

    async for message in query(prompt=prompt, options=options):
        if hasattr(message, "content"):
            for block in message.content:
                if hasattr(block, "text"):
                    response_parts.append(block.text)

    result = "\n".join(response_parts) if response_parts else "No trends discovered."

    from src.shared.activity_log import append_log
    append_log("trend", "Trend discovery finished", f"{len(result)} chars")

    logger.info("Trend discovery finished (%d chars output).", len(result))
    return result


def main() -> None:
    """Entry point for running trend discovery."""
    asyncio.run(run_trend())


if __name__ == "__main__":
    main()
