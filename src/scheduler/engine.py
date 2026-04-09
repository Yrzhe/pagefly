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
        summary = result[:3500] + "..." if len(result) > 3500 else result
        await notify(f"{review_type.title()} Review\n\n{summary}")
    except Exception as e:
        logger.error("%s review failed: %s", review_type, e)
        await notify(f"{review_type.title()} review failed: {e}")


async def _run_lint() -> None:
    """Scheduled task: run wiki lint / health check."""
    logger.info("Scheduled wiki lint starting...")
    try:
        from src.agents.review import run_review
        result = await run_review("lint")
        summary = result[:500] + "..." if len(result) > 500 else result
        await notify(f"Wiki Lint Report\n\n{summary}")
    except Exception as e:
        logger.error("Wiki lint failed: %s", e)
        await notify(f"Wiki lint failed: {e}")


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
        loop = asyncio.get_running_loop()
        processed = await loop.run_in_executor(None, scan_and_organize)
        if processed:
            await notify(f"Organized {len(processed)} document(s) from raw/ to knowledge/.")
    except Exception as e:
        logger.error("Organize failed: %s", e)


async def _catchup_chat_archive() -> None:
    """On startup, check if yesterday's chat archive was missed and run it if so."""
    from datetime import timedelta
    from src.storage import db as database

    await asyncio.sleep(10)  # Wait for bot to initialize

    yesterday = (datetime.now(timezone.utc).astimezone() - timedelta(days=1)).strftime("%Y-%m-%d")

    conn = database.get_connection()
    row = conn.execute(
        "SELECT COUNT(*) FROM documents WHERE original_filename LIKE ? OR ingested_at LIKE ?",
        (f"chat_{yesterday}%", f"{yesterday}%"),
    ).fetchone()
    conn.close()

    # Also check if there are any messages from yesterday worth archiving
    all_sessions = database.load_all_sessions()
    has_yesterday_msgs = False
    for cid, msgs in all_sessions.items():
        for m in msgs:
            ts = m.get("ts", "")
            if ts and yesterday in ts:
                has_yesterday_msgs = True
                break

    if row[0] == 0 and has_yesterday_msgs:
        logger.info("Missed archive for %s detected, running catch-up...", yesterday)
        try:
            from src.channels.telegram import _save_daily_chat, _sessions
            from src.agents.query import QuerySession

            # Hydrate in-memory sessions from DB so _save_daily_chat has data
            all_sessions = database.load_all_sessions()
            for cid, msgs in all_sessions.items():
                if cid not in _sessions and msgs:
                    _sessions[cid] = (QuerySession(messages=msgs), datetime.now(timezone.utc).timestamp())

            await _save_daily_chat(None)
            logger.info("Catch-up archive for %s completed", yesterday)
        except Exception as e:
            logger.error("Catch-up archive failed: %s", e)
    else:
        logger.info("Archive for %s already exists, no catch-up needed", yesterday)


async def _run_workspace_organize() -> None:
    """Scheduled task: LLM-powered workspace triage."""
    logger.info("Scheduled workspace organize starting...")
    try:
        from src.governance.workspace_organizer import organize_workspace
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, organize_workspace)
        if result["deleted"] + result["ingested"] > 0:
            summary = f"Workspace organized: {result['deleted']} deleted, {result['ingested']} ingested, {result['kept']} kept"
            await notify(summary)
        else:
            logger.info("Workspace organize: nothing to do")
    except Exception as e:
        logger.error("Workspace organize failed: %s", e)
        await notify(f"Workspace organize failed: {e}")


async def _cleanup_workspace() -> None:
    """Remove workspace files older than 7 days."""
    from src.shared.config import WORKSPACE_DIR

    if not WORKSPACE_DIR.exists():
        return

    now = datetime.now(timezone.utc).astimezone()
    removed = 0
    for file_path in list(WORKSPACE_DIR.rglob("*")):
        if file_path.is_dir():
            continue
        mtime = datetime.fromtimestamp(file_path.stat().st_mtime, tz=timezone.utc).astimezone()
        age_days = (now - mtime).days
        if age_days >= 7:
            file_path.unlink()
            removed += 1
            logger.info("Workspace cleanup: removed %s (age=%dd)", file_path.name, age_days)

    # Remove empty directories
    for dir_path in sorted(WORKSPACE_DIR.rglob("*"), reverse=True):
        if dir_path.is_dir() and not any(dir_path.iterdir()):
            dir_path.rmdir()

    if removed:
        logger.info("Workspace cleanup: removed %d files", removed)


async def _run_custom_task(task_name: str, task_type: str, prompt: str) -> None:
    """Run a user-defined scheduled task."""
    logger.info("Running custom task: %s (%s)", task_name, task_type)
    try:
        if task_type == "review":
            from src.agents.review import run_review
            result = await run_review("daily")
            summary = result[:500] + "..." if len(result) > 500 else result
            await notify(f"Custom Review: {task_name}\n\n{summary}")
        elif task_type == "compiler":
            from src.agents.compiler import run_compiler
            await run_compiler()
            await notify(f"Custom Compiler: {task_name} finished.")
        elif task_type == "custom":
            # Run as a generic agent query with the custom prompt
            from src.agents.query import ask
            result = await ask(prompt)
            summary = result[:500] + "..." if len(result) > 500 else result
            await notify(f"Task: {task_name}\n\n{summary}")
        else:
            logger.warning("Unknown task type: %s", task_type)
    except Exception as e:
        logger.error("Custom task %s failed: %s", task_name, e)
        await notify(f"Task '{task_name}' failed: {e}")


def _load_user_tasks(scheduler: AsyncIOScheduler) -> None:
    """Load user-defined scheduled tasks from database."""
    from src.storage import db
    tasks = db.list_scheduled_tasks(enabled_only=True)

    for task in tasks:
        job_id = f"user_{task['id'][:8]}"
        try:
            scheduler.add_job(
                _run_custom_task,
                args=[task["name"], task["task_type"], task["prompt"]],
                trigger=CronTrigger(**_parse_cron(task["cron_expr"])),
                id=job_id,
                name=f"[User] {task['name']}",
                replace_existing=True,
            )
            logger.info("Loaded user task: %s (%s)", task["name"], task["cron_expr"])
        except Exception as e:
            logger.error("Failed to load task %s: %s", task["name"], e)


def _reload_user_tasks(scheduler: AsyncIOScheduler) -> None:
    """Reload user tasks — add new, update changed, remove deleted."""
    from src.storage import db
    tasks = db.list_scheduled_tasks(enabled_only=True)
    db_job_ids = {f"user_{t['id'][:8]}" for t in tasks}

    # Remove jobs that are no longer in DB
    for job in scheduler.get_jobs():
        if job.id.startswith("user_") and job.id not in db_job_ids:
            scheduler.remove_job(job.id)
            logger.info("Removed stale job: %s", job.name)

    # Add/update jobs from DB
    for task in tasks:
        job_id = f"user_{task['id'][:8]}"
        try:
            scheduler.add_job(
                _run_custom_task,
                args=[task["name"], task["task_type"], task["prompt"]],
                trigger=CronTrigger(**_parse_cron(task["cron_expr"])),
                id=job_id,
                name=f"[User] {task['name']}",
                replace_existing=True,
            )
        except Exception as e:
            logger.error("Failed to reload task %s: %s", task["name"], e)


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

    # Wiki lint (Sunday 3am)
    scheduler.add_job(
        _run_lint,
        trigger=CronTrigger(day_of_week="sun", hour=3, minute=0),
        id="wiki_lint", name="Wiki Lint",
    )

    # Workspace organizer (daily at 3:30am — LLM-powered triage)
    scheduler.add_job(
        _run_workspace_organize,
        trigger=CronTrigger(hour=3, minute=30),
        id="workspace_organize", name="Workspace Organize",
    )

    # Load user-defined tasks from database
    _load_user_tasks(scheduler)

    scheduler.start()

    jobs = scheduler.get_jobs()
    for job in jobs:
        logger.info("Scheduled: %s (next run: %s)", job.name, job.next_run_time)

    # Periodically reload user tasks (checks for new/updated/deleted tasks)
    async def _reload_loop():
        while True:
            await asyncio.sleep(60)
            _reload_user_tasks(scheduler)

    reload_task = asyncio.create_task(_reload_loop())

    # Catch-up: check if yesterday's chat archive was missed (e.g., due to restart)
    asyncio.create_task(_catchup_chat_archive())

    logger.info("Scheduler started with %d jobs + inbox watcher + live reload", len(jobs))
    await watch_inbox()
