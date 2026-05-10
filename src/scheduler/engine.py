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
    TELEGRAM_CHAT_ID,
)
from src.shared.logger import get_logger
from src.scheduler.notifier import notify
from src.scheduler.watcher import watch_inbox
from src.storage.db import init_db

logger = get_logger("scheduler.engine")


def _inject_push_context(task_name: str, preview: str) -> None:
    """Inject a system push notification into the chat session.

    This ensures the Query Agent knows what scheduled tasks just ran,
    so the user can discuss the results in the next message.
    """
    if not TELEGRAM_CHAT_ID:
        return
    try:
        from src.channels.telegram import _get_session, _persist_session

        chat_id = int(TELEGRAM_CHAT_ID)
        session = _get_session(chat_id)
        ts = datetime.now(timezone.utc).astimezone().isoformat()
        truncated = preview[:500] if preview else "(no output)"
        context = (
            f"[System: Scheduled task '{task_name}' completed and results were "
            f"sent to the user. Summary:\n{truncated}]"
        )
        session.messages.append({"role": "assistant", "content": context, "ts": ts})
        _persist_session(chat_id)
    except Exception as e:
        logger.debug("Failed to inject push context for %s: %s", task_name, e)


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
        _inject_push_context("Compiler", "New wiki articles generated from recent knowledge documents.")
    except Exception as e:
        logger.error("Compiler failed: %s", e)
        await notify(f"Compiler failed: {e}")


async def _run_linker() -> None:
    """Scheduled task: run linker agent to discover missing connections."""
    logger.info("Scheduled linker starting...")
    try:
        from src.agents.linker import run_linker
        result = await run_linker()
        preview = (result or "")[:300].replace("\n", " ")
        await notify(f"Linker finished.\n\n{preview}")
        _inject_push_context("Linker", preview)
    except Exception as e:
        logger.error("Linker failed: %s", e)
        await notify(f"Linker failed: {e}")


async def _run_trend() -> None:
    """Scheduled task: run trend discovery agent."""
    logger.info("Scheduled trend discovery starting...")
    try:
        from src.agents.trend import run_trend
        result = await run_trend()
        preview = (result or "")[:300].replace("\n", " ")
        await notify(f"Trend Discovery finished.\n\n{preview}")
        _inject_push_context("Trend Discovery", preview)
    except Exception as e:
        logger.error("Trend discovery failed: %s", e)
        await notify(f"Trend discovery failed: {e}")


async def _run_daily_roam() -> None:
    """Scheduled task: push random knowledge documents for resurfacing."""
    logger.info("Daily Roam starting...")
    try:
        from src.shared.roam import pick_roam_docs, format_roam_message
        from src.shared.config import TELEGRAM_CHAT_ID

        items = pick_roam_docs(count=3)
        if not items:
            logger.info("Daily Roam: no documents to resurface")
            return

        message = format_roam_message(items)
        await notify(message)

        # Inject into chat context so Query Agent knows what was pushed
        if TELEGRAM_CHAT_ID:
            try:
                from src.channels.telegram import _get_session, _persist_session
                from datetime import datetime as dt, timezone

                chat_id = int(TELEGRAM_CHAT_ID)
                session = _get_session(chat_id)
                ts = dt.now(timezone.utc).astimezone().isoformat()
                summaries = [f"{it['title']} [{it['category']}]: {it['preview'][:100]}" for it in items]
                context = (
                    "[System: Daily Random Roam was just sent to the user. "
                    "These documents were resurfaced for review:\n"
                    + "\n".join(f"- {s}" for s in summaries)
                    + "\nThe user may want to discuss these topics.]"
                )
                session.messages.append({"role": "assistant", "content": context, "ts": ts})
                _persist_session(chat_id)
            except Exception as e:
                logger.debug("Failed to inject roam context: %s", e)

    except Exception as e:
        logger.error("Daily Roam failed: %s", e)
        await notify(f"Daily Roam failed: {e}")


async def _run_review(review_type: str) -> None:
    """Scheduled task: run review agent."""
    logger.info("Scheduled %s review starting...", review_type)
    try:
        from src.agents.review import run_review
        result = await run_review(review_type)

        # Find the latest review article and send as file
        from src.storage.db import get_connection
        conn = get_connection()
        row = conn.execute(
            "SELECT file_path FROM wiki_articles WHERE article_type='review' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        conn.close()

        file_path = None
        if row:
            from pathlib import Path
            md_path = Path(row["file_path"]) / "document.md"
            if md_path.exists():
                file_path = str(md_path)

        await notify(f"{review_type.title()} Review completed", file_path=file_path)
        _inject_push_context(
            f"{review_type.title()} Review",
            (result or "")[:500],
        )
    except Exception as e:
        logger.error("%s review failed: %s", review_type, e)
        await notify(f"{review_type.title()} review failed: {e}")


async def _run_lint() -> None:
    """Scheduled task: run wiki lint / health check."""
    logger.info("Scheduled wiki lint starting...")
    try:
        from src.agents.review import run_review
        result = await run_review("lint")

        from src.storage.db import get_connection
        conn = get_connection()
        row = conn.execute(
            "SELECT file_path FROM wiki_articles WHERE article_type='lint' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        conn.close()

        file_path = None
        if row:
            from pathlib import Path
            md_path = Path(row["file_path"]) / "document.md"
            if md_path.exists():
                file_path = str(md_path)

        await notify("Wiki Lint Report completed", file_path=file_path)
        _inject_push_context("Wiki Lint", (result or "")[:500])
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
    today = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")

    conn = database.get_connection()
    # Check if yesterday OR today archive already exists
    # (_save_daily_chat archives "today's" messages, not yesterday's)
    row = conn.execute(
        "SELECT COUNT(*) FROM documents WHERE original_filename LIKE ? OR original_filename LIKE ?",
        (f"chat_{yesterday}%", f"chat_{today}%"),
    ).fetchone()
    conn.close()

    if row[0] > 0:
        logger.info("Chat archive already exists for %s or %s (%d docs), skipping catch-up", yesterday, today, row[0])
        return

    # Check if there are any messages from yesterday worth archiving
    all_sessions = database.load_all_sessions()
    has_yesterday_msgs = False
    for cid, msgs in all_sessions.items():
        for m in msgs:
            ts = m.get("ts", "")
            if ts and yesterday in ts:
                has_yesterday_msgs = True
                break

    if not has_yesterday_msgs:
        logger.info("No messages from %s to archive, skipping catch-up", yesterday)
        return

    logger.info("Missed archive for %s detected, running catch-up...", yesterday)
    try:
        from src.channels.telegram import _save_daily_chat, _sessions
        from src.agents.query import QuerySession

        all_sessions = database.load_all_sessions()
        for cid, msgs in all_sessions.items():
            if cid not in _sessions and msgs:
                _sessions[cid] = (QuerySession(messages=msgs), datetime.now(timezone.utc).timestamp())

        await _save_daily_chat(None)
        logger.info("Catch-up archive for %s completed", yesterday)
    except Exception as e:
        logger.error("Catch-up archive failed: %s", e)


async def _run_activity_log() -> None:
    """Scheduled task: summarize yesterday's desktop activity into a wiki article."""
    logger.info("Scheduled activity_log starting...")
    try:
        from src.agents.activity_log import run_activity_log
        result = await run_activity_log()
        preview = (result or "")[:200].replace("\n", " ")
        await notify(f"Work log generated.\n\n{preview}")
    except Exception as e:
        logger.error("Activity log failed: %s", e)
        await notify(f"Activity log failed: {e}")


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


_TELEGRAM_MAX_CHARS = 3500


async def _notify_run_result(
    task_name: str,
    task_type: str,
    status: str,
    output: str,
    error: str,
    run_id: int | None,
) -> None:
    """Send Telegram notification, truncating long output and pointing to dashboard."""
    if status == "failed":
        msg = f"❌ {task_name} ({task_type}) failed\n\n{error[:1500]}"
        if run_id:
            msg += f"\n\nRun #{run_id} — see Schedules tab for details"
        try:
            await notify(msg)
        except Exception as e:
            logger.warning("notify failed: %s", e)
        return

    body = (output or "").strip() or f"{task_name} completed."
    header = f"✅ {task_name} ({task_type})"

    if len(body) > _TELEGRAM_MAX_CHARS:
        truncated = body[:_TELEGRAM_MAX_CHARS]
        suffix = f"\n\n…(truncated)\n\nRun #{run_id} — see Schedules tab for full output" if run_id else "\n\n…(truncated)"
        msg = f"{header}\n\n{truncated}{suffix}"
    else:
        msg = f"{header}\n\n{body}"
        if run_id:
            msg += f"\n\nRun #{run_id}"

    try:
        await notify(msg)
    except Exception as e:
        logger.warning("notify failed: %s", e)


async def _run_with_recording(
    task_id: str | None,
    task_name: str,
    task_type: str,
    runner,
    source: str = "user",
) -> None:
    """Wrap a task coroutine to record execution + notify result. Never raises."""
    import time
    from src.storage import db

    run_id: int | None = None
    try:
        run_id = db.insert_task_run(task_id, task_name, task_type, source)
    except Exception as e:
        logger.warning("Could not insert task_run: %s", e)

    started = time.time()
    output = ""
    error_msg = ""
    status = "success"

    try:
        result = await runner
        if isinstance(result, str):
            output = result
        elif result is not None:
            output = str(result)
    except Exception as e:
        status = "failed"
        error_msg = f"{type(e).__name__}: {e}"
        logger.error("Task %s failed: %s", task_name, e, exc_info=True)

    duration_ms = int((time.time() - started) * 1000)

    if run_id is not None:
        try:
            db.finish_task_run(run_id, status, output, error_msg, duration_ms)
        except Exception as e:
            logger.warning("Could not finish task_run %s: %s", run_id, e)

    await _notify_run_result(task_name, task_type, status, output, error_msg, run_id)


_IN_FLIGHT: set[str] = set()


async def _run_custom_task(task_id: str, task_name: str, task_type: str, prompt: str) -> None:
    """Run a user-defined scheduled task with execution recording."""
    # Per-task in-flight guard: if a scheduled run and a manual run-now collide,
    # skip the second invocation instead of recording a duplicate run.
    if task_id and task_id in _IN_FLIGHT:
        logger.warning("Task %s already running, skipping duplicate invocation", task_name)
        return
    if task_id:
        _IN_FLIGHT.add(task_id)

    logger.info("Running custom task: %s (%s) id=%s", task_name, task_type, task_id[:8] if task_id else "-")

    try:
        await _dispatch_custom_task(task_id, task_name, task_type, prompt)
    finally:
        _IN_FLIGHT.discard(task_id)


async def _dispatch_custom_task(task_id: str, task_name: str, task_type: str, prompt: str) -> None:
    # Build the runner coroutine based on task_type. Both 'custom' and 'ingest'
    # delegate to the query agent — same brain as the Telegram bot, with all
    # MCP tools (read/write knowledge, search, ingest URLs, compile wiki, etc.)
    if task_type == "review":
        from src.agents.review import run_review
        runner = run_review("daily")
    elif task_type == "compiler":
        from src.agents.compiler import run_compiler
        runner = run_compiler()
    elif task_type == "linker":
        from src.agents.linker import run_linker
        runner = run_linker()
    elif task_type == "trend":
        from src.agents.trend import run_trend
        runner = run_trend()
    elif task_type in ("custom", "ingest"):
        from src.agents.query import ask
        effective_prompt = prompt.strip() or f"Run scheduled task: {task_name}"
        runner = ask(effective_prompt)
    else:
        logger.warning("Unknown task type: %s — falling back to query agent", task_type)
        from src.agents.query import ask
        runner = ask(prompt.strip() or f"Run scheduled task: {task_name}")

    await _run_with_recording(task_id, task_name, task_type, runner, source="user")


def _load_user_tasks(scheduler: AsyncIOScheduler) -> None:
    """Load user-defined scheduled tasks from database."""
    from src.storage import db
    tasks = db.list_scheduled_tasks(enabled_only=True)

    for task in tasks:
        job_id = f"user_{task['id'][:8]}"
        try:
            scheduler.add_job(
                _run_custom_task,
                args=[task["id"], task["name"], task["task_type"], task["prompt"]],
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
                args=[task["id"], task["name"], task["task_type"], task["prompt"]],
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

    # Linker (Wednesday 3am — midweek connection discovery)
    scheduler.add_job(
        _run_linker,
        trigger=CronTrigger(day_of_week="wed", hour=3, minute=0),
        id="linker", name="Linker",
    )

    # Trend discovery (Friday 9am — end-of-week insights)
    scheduler.add_job(
        _run_trend,
        trigger=CronTrigger(day_of_week="fri", hour=9, minute=0),
        id="trend_discovery", name="Trend Discovery",
    )

    # Daily Random Roam (every day at 10am — resurface old knowledge)
    scheduler.add_job(
        _run_daily_roam,
        trigger=CronTrigger(hour=10, minute=0),
        id="daily_roam", name="Daily Roam",
    )

    # Workspace organizer (daily at 3:30am — LLM-powered triage)
    scheduler.add_job(
        _run_workspace_organize,
        trigger=CronTrigger(hour=3, minute=30),
        id="workspace_organize", name="Workspace Organize",
    )

    # Activity log (daily at 8:00am — summarize yesterday's desktop capture)
    scheduler.add_job(
        _run_activity_log,
        trigger=CronTrigger(hour=8, minute=0),
        id="activity_log", name="Activity Log",
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
