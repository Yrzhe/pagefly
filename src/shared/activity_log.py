"""Append-only activity log — human + LLM readable timeline.

Current week's log lives at data/log.md.
On each write, if the current week has changed, the previous log is
archived to: data/log_archive/YYYY/MM/week-WW.md
(month is determined by the Monday of that week)
"""

from datetime import datetime, timezone, timedelta
from pathlib import Path

from src.shared.config import DATA_DIR
from src.shared.logger import get_logger

logger = get_logger("shared.activity_log")

LOG_PATH = DATA_DIR / "log.md"
ARCHIVE_DIR = DATA_DIR / "log_archive"
_WEEK_TAG = "<!-- week:"  # hidden tag to track which week this log belongs to


def _now() -> datetime:
    """Current local time."""
    return datetime.now(timezone.utc).astimezone()


def _iso_week_key(dt: datetime) -> str:
    """Return 'YYYY-WNN' ISO week key, e.g. '2026-W15'."""
    year, week, _ = dt.isocalendar()
    return f"{year}-W{week:02d}"


def _monday_of_week(dt: datetime) -> datetime:
    """Return the Monday of the ISO week containing dt."""
    return dt - timedelta(days=dt.weekday())


def _archive_path_for(dt: datetime) -> Path:
    """Build archive path: log_archive/YYYY/MM/week-WW.md
    Month is determined by the Monday of that week."""
    monday = _monday_of_week(dt)
    year, week, _ = dt.isocalendar()
    return ARCHIVE_DIR / str(monday.year) / f"{monday.month:02d}" / f"week-{week:02d}.md"


def _read_week_tag() -> str | None:
    """Read the week tag from current log.md, if it exists."""
    if not LOG_PATH.exists():
        return None
    first_line = LOG_PATH.open(encoding="utf-8").readline().strip()
    if first_line.startswith(_WEEK_TAG):
        return first_line.replace(_WEEK_TAG, "").replace("-->", "").strip()
    return None


def _new_log_header(week_key: str) -> str:
    """Create the header for a new week's log."""
    return (
        f"{_WEEK_TAG} {week_key} -->\n"
        f"# Activity Log — {week_key}\n\n"
    )


def _rotate_if_needed() -> None:
    """If the current week differs from the log's week, archive the old log."""
    now = _now()
    current_week = _iso_week_key(now)
    log_week = _read_week_tag()

    if log_week is None or log_week == current_week:
        return

    if not LOG_PATH.exists():
        return

    content = LOG_PATH.read_text(encoding="utf-8")
    if not content.strip():
        return

    # Parse the old week to determine the archive path
    # log_week format: "YYYY-WNN"
    try:
        old_year = int(log_week.split("-W")[0])
        old_week = int(log_week.split("-W")[1])
        # Reconstruct a datetime for the old Monday
        old_monday = datetime.strptime(f"{old_year}-W{old_week:02d}-1", "%G-W%V-%u")
        old_monday = old_monday.replace(tzinfo=now.tzinfo)
    except (ValueError, IndexError):
        # Fallback: use last week
        old_monday = _monday_of_week(now) - timedelta(weeks=1)

    archive = _archive_path_for(old_monday)
    archive.parent.mkdir(parents=True, exist_ok=True)

    # Append to existing archive if same week file exists
    if archive.exists():
        existing = archive.read_text(encoding="utf-8")
        archive.write_text(existing + "\n" + content, encoding="utf-8")
    else:
        archive.write_text(content, encoding="utf-8")

    # Start fresh log for current week
    LOG_PATH.write_text(_new_log_header(current_week), encoding="utf-8")
    logger.info("Activity log rotated: %s → %s", log_week, archive)


def append_log(event_type: str, title: str, details: str = "") -> None:
    """
    Append an entry to data/log.md.

    Args:
        event_type: ingest | classify | compile | review | query | lint
        title: short description of the event
        details: optional multi-line details
    """
    _rotate_if_needed()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    now = _now()
    current_week = _iso_week_key(now)

    # Create log with week header if it doesn't exist
    if not LOG_PATH.exists():
        LOG_PATH.write_text(_new_log_header(current_week), encoding="utf-8")

    # If existing log has no week tag (legacy), add one
    if _read_week_tag() is None:
        existing = LOG_PATH.read_text(encoding="utf-8")
        LOG_PATH.write_text(_new_log_header(current_week) + existing, encoding="utf-8")

    timestamp = now.strftime("%Y-%m-%d %H:%M")
    entry = f"## [{timestamp}] {event_type} | {title}\n"
    if details:
        for line in details.strip().split("\n"):
            entry += f"{line}\n"
    entry += "\n"

    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(entry)

    logger.debug("Activity logged: %s | %s", event_type, title)
