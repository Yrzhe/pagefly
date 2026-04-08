"""PageFly entry point — runs API, Telegram bot, scheduler, and watcher."""

import asyncio
import threading

from src.shared.config import API_PORT, TELEGRAM_BOT_TOKEN
from src.shared.logger import get_logger
from src.storage.db import init_db

logger = get_logger("main")


def _run_api_server() -> None:
    """Run FastAPI server in a separate thread."""
    import uvicorn
    uvicorn.run("src.channels.api:app", host="0.0.0.0", port=API_PORT, log_level="info")


async def _main() -> None:
    """Start all services in one event loop."""
    init_db()
    logger.info("PageFly starting...")

    # API server in background thread (always — health endpoint needs it)
    api_thread = threading.Thread(target=_run_api_server, daemon=True)
    api_thread.start()
    logger.info("API server started on port %d", API_PORT)

    # Telegram bot (async, in main loop — needs main thread for signal handling)
    bot_app = None
    if TELEGRAM_BOT_TOKEN and TELEGRAM_BOT_TOKEN != "xxx":
        from src.channels.telegram import start_bot
        try:
            bot_app = await start_bot()
        except Exception as e:
            logger.error("Telegram bot failed to start: %s", e)
    else:
        logger.info("Telegram not configured, skipping bot")

    # Scheduler + inbox watcher (blocking)
    from src.scheduler.engine import start_scheduler
    try:
        await start_scheduler()
    finally:
        if bot_app:
            from src.channels.telegram import stop_bot
            await stop_bot()


def main() -> None:
    """Entry point."""
    asyncio.run(_main())


if __name__ == "__main__":
    main()
