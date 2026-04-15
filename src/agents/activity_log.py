"""Activity Log Agent — summarizes a day of desktop capture into a wiki article.

Reads `activity_events` + joined `audio_recordings` transcripts for the target
day, injects them into a focused prompt, and delegates writing to the review
agent infrastructure (which already has wiki tools wired up).
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from claude_agent_sdk import query

from src.agents.base import build_agent_options
from src.shared.logger import get_logger
from src.storage import db

logger = get_logger("agents.activity_log")

_MAX_EVENTS_IN_PROMPT = 400
_MAX_TEXT_PER_EVENT = 400
_MAX_TRANSCRIPTS_IN_PROMPT = 10


def _default_target_date() -> str:
    """Yesterday in local time, YYYY-MM-DD."""
    local = datetime.now(timezone.utc).astimezone()
    y = local - timedelta(days=1)
    return y.strftime("%Y-%m-%d")


def _load_day(date_str: str) -> tuple[list[dict], list[dict]]:
    """Return (events, audio_rows) for the day."""
    start = f"{date_str}T00:00:00"
    end_dt = datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)
    end = end_dt.strftime("%Y-%m-%dT00:00:00")

    events = db.list_activity_events(start=start, end=end, limit=_MAX_EVENTS_IN_PROMPT * 2)
    # Collect audio ids referenced by events
    audio_ids = sorted({e["audio_id"] for e in events if e.get("audio_id")})
    audio_rows = [db.get_audio_recording(aid) for aid in audio_ids]
    audio_rows = [a for a in audio_rows if a and a.get("transcript")]
    return events, audio_rows


def _summarize_by_app(events: list[dict]) -> list[dict]:
    """Collapse events into per-app rollups to keep the prompt compact."""
    by_app: dict[str, dict] = defaultdict(
        lambda: {"app": "", "duration_s": 0, "sessions": 0, "titles": [], "urls": set()}
    )
    for e in events:
        key = e.get("app") or "Unknown"
        b = by_app[key]
        b["app"] = key
        b["duration_s"] += int(e.get("duration_s") or 0)
        b["sessions"] += 1
        title = e.get("window_title") or ""
        if title and title not in b["titles"] and len(b["titles"]) < 8:
            b["titles"].append(title)
        url = e.get("url") or ""
        if url:
            b["urls"].add(url)
    out = sorted(by_app.values(), key=lambda x: x["duration_s"], reverse=True)
    for b in out:
        b["urls"] = sorted(b["urls"])[:6]
    return out


def _build_prompt(date_str: str, events: list[dict], audio_rows: list[dict]) -> str:
    rollup = _summarize_by_app(events)
    total_duration_min = sum(b["duration_s"] for b in rollup) // 60

    lines: list[str] = []
    lines.append(f"# Activity data for {date_str}")
    lines.append(
        f"{len(events)} context events across {len(rollup)} apps, total tracked "
        f"time: ~{total_duration_min} min."
    )
    lines.append("")
    lines.append("## Per-app rollup (duration desc)")
    for b in rollup[:20]:
        mins = b["duration_s"] // 60
        title_sample = "; ".join(b["titles"][:3]) if b["titles"] else ""
        url_sample = ", ".join(b["urls"][:3]) if b["urls"] else ""
        extra = f" · {title_sample}" if title_sample else ""
        if url_sample:
            extra += f" · urls: {url_sample}"
        lines.append(f"- **{b['app']}** — {mins} min, {b['sessions']} sessions{extra}")

    lines.append("")
    lines.append("## Sample events (chronological, truncated)")
    for e in events[:_MAX_EVENTS_IN_PROMPT]:
        txt = (e.get("text_excerpt") or "")[:_MAX_TEXT_PER_EVENT]
        ts = e.get("started_at", "")[:19]
        parts = [ts, e.get("app", ""), e.get("window_title", "")[:60]]
        if e.get("url"):
            parts.append(e["url"][:80])
        line = " | ".join(p for p in parts if p)
        if txt:
            line += f"\n  > {txt}"
        lines.append(f"- {line}")

    if audio_rows:
        lines.append("")
        lines.append(f"## Audio transcripts ({len(audio_rows)})")
        for a in audio_rows[:_MAX_TRANSCRIPTS_IN_PROMPT]:
            trig = f" ({a['trigger_app']})" if a.get("trigger_app") else ""
            dur = a.get("duration_s", 0) // 60
            lines.append(f"### {a.get('started_at', '')}{trig} — {dur} min")
            lines.append((a.get("transcript") or "")[:4000])
            lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        f"Task: write a concise **Work log {date_str}** wiki article summarizing "
        f"the above activity. Structure it as:\n"
        f"1. One-paragraph TL;DR of what the user did today.\n"
        f"2. A **Time breakdown** section listing top apps with durations.\n"
        f"3. A **Focus areas** section grouping related sessions into themes "
        f"(e.g. 'Shipped PageFly scheduler panel', 'Read 3 papers on agents').\n"
        f"4. A **Meeting notes** section with bullet summaries per transcript, if any.\n"
        f"5. A short **Open threads** section flagging unfinished work worth "
        f"following up tomorrow.\n\n"
        f"Use the write_wiki_article tool with article_type='review', "
        f"title='Work log {date_str}', and a brief summary. "
        f"Be faithful to the data — don't invent details."
    )
    return "\n".join(lines)


async def run_activity_log(date_str: str | None = None) -> str:
    """Generate the work-log wiki article for a given day (default: yesterday)."""
    db.init_db()
    target = date_str or _default_target_date()
    events, audio_rows = _load_day(target)

    if not events and not audio_rows:
        msg = f"No activity data for {target} — skipping work log."
        logger.info(msg)
        return msg

    prompt = _build_prompt(target, events, audio_rows)

    options = build_agent_options(
        skill_name="review",
        extra_system=f"Context: generating a Work log for {target} from desktop capture data.",
    )

    logger.info(
        "Running activity_log for %s (%d events, %d transcripts, %d prompt chars)",
        target, len(events), len(audio_rows), len(prompt),
    )

    parts: list[str] = []
    async for msg in query(prompt=prompt, options=options):
        if hasattr(msg, "content"):
            for block in msg.content:
                if hasattr(block, "text"):
                    parts.append(block.text)

    response = "\n".join(parts) or f"Activity log for {target} generated."
    logger.info("activity_log complete for %s (%d chars)", target, len(response))
    return response
