"""Unified scheduler — manages all cron jobs and the inbox watcher."""

import asyncio
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.shared.config import (
    SCHEDULE_CHAT_ARCHIVE,
    SCHEDULE_COMPILER,
    SCHEDULE_DAILY_REVIEW,
    SCHEDULE_MONTHLY_REVIEW,
    SCHEDULE_WEEKLY_REVIEW,
)
from src.shared.logger import get_logger
from src.scheduler.notifier import notify
from src.scheduler.watcher import watch_inbox
from src.storage.db import init_db

logger = get_logger("scheduler.engine")


def _parse_cron(expr: str) -> dict:
    """Parse a cron expression into APScheduler kwargs."""
    parts = expr.strip().split()
    if len(parts) != 5:
        raise ValueError(f"Invalid cron expression: {expr}")
    return {
        "minute": parts[0],
        "hour": parts[1],
        "day": parts[2],
        "month": parts[3],
        "day_of_week": parts[4],
    }


async def _run_compiler() -> None:
    """Scheduled task: run compiler agent."""
    logger.info("Scheduled compiler starting...")
    try:
        from src.agents.compiler import run_compiler
        await run_compiler()
        await notify("Compiler finished — new wiki articles generated.")
    except Exception as e:
        logger.error("Compiler failed: %s", e)
        await notify(f"Compiler failed: {e}")


async def _run_review(review_type: str) -> None:
    """Scheduled task: run review agent."""
    logger.info("Scheduled %s review starting...", review_type)
    try:
        from src.agents.review import run_review
        result = await run_review(review_type)
        summary = result[:500] + "..." if len(result) > 500 else result
        await notify(f"{review_type.title()} Review\n\n{summary}")
    except Exception as e:
        logger.error("%s review failed: %s", review_type, e)
        await notify(f"{review_type.title()} review failed: {e}")


async def _run_chat_archive() -> None:
    """Scheduled task: archive daily chat logs."""
    logger.info("Archiving daily chat logs...")
    try:
        from src.channels.telegram import _sessions, _save_daily_chat
        # Create a minimal context-like object for the job
        await _save_daily_chat(None)
        await notify("Daily chat log archived.")
    except Exception as e:
        logger.error("Chat archive failed: %s", e)


async def _run_organize() -> None:
    """Process any documents in raw/ that need organizing."""
    try:
        from src.governance.organizer import scan_and_organize
        loop = asyncio.get_event_loop()
        processed = await loop.run_in_executor(None, scan_and_organize)
        if processed:
            await notify(f"Organized {len(processed)} document(s) from raw/ to knowledge/.")
    except Exception as e:
        logger.error("Organize failed: %s", e)


async def start_scheduler() -> None:
    """Start the unified scheduler with all configured jobs."""
    init_db()

    scheduler = AsyncIOScheduler()

    # Register cron jobs
    scheduler.add_job(
        _run_review, args=["daily"],
        trigger=CronTrigger(**_parse_cron(SCHEDULE_DAILY_REVIEW)),
        id="daily_review", name="Daily Review",
    )
    scheduler.add_job(
        _run_review, args=["weekly"],
        trigger=CronTrigger(**_parse_cron(SCHEDULE_WEEKLY_REVIEW)),
        id="weekly_review", name="Weekly Review",
    )
    scheduler.add_job(
        _run_review, args=["monthly"],
        trigger=CronTrigger(**_parse_cron(SCHEDULE_MONTHLY_REVIEW)),
        id="monthly_review", name="Monthly Review",
    )
    scheduler.add_job(
        _run_compiler,
        trigger=CronTrigger(**_parse_cron(SCHEDULE_COMPILER)),
        id="compiler", name="Compiler",
    )
    scheduler.add_job(
        _run_chat_archive,
        trigger=CronTrigger(**_parse_cron(SCHEDULE_CHAT_ARCHIVE)),
        id="chat_archive", name="Chat Archive",
    )

    scheduler.start()

    jobs = scheduler.get_jobs()
    for job in jobs:
        logger.info("Scheduled: %s (next run: %s)", job.name, job.next_run_time)

    # Start inbox watcher alongside scheduler
    logger.info("Scheduler started with %d jobs + inbox watcher", len(jobs))
    await watch_inbox()
