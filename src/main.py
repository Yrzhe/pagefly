"""PageFly entry point — runs API, scheduler, watcher, and optionally Telegram bot."""

import asyncio
import threading

from src.shared.config import API_PORT, API_MASTER_TOKEN, TELEGRAM_BOT_TOKEN
from src.shared.logger import get_logger
from src.storage.db import init_db

logger = get_logger("main")


def _run_telegram_bot() -> None:
    """Run Telegram bot in a separate thread (it has its own event loop)."""
    from src.channels.telegram import run_bot
    try:
        run_bot()
    except Exception as e:
        logger.error("Telegram bot error: %s", e)


def _run_api_server() -> None:
    """Run FastAPI server in a separate thread."""
    import uvicorn
    uvicorn.run("src.channels.api:app", host="0.0.0.0", port=API_PORT, log_level="info")


async def _run_scheduler() -> None:
    """Run the unified scheduler + inbox watcher."""
    from src.scheduler.engine import start_scheduler
    await start_scheduler()


def main() -> None:
    """Start PageFly system — all services."""
    init_db()
    logger.info("PageFly starting...")

    # Start API server in background thread
    if API_MASTER_TOKEN:
        api_thread = threading.Thread(target=_run_api_server, daemon=True)
        api_thread.start()
        logger.info("API server started on port %d", API_PORT)
    else:
        logger.info("API token not configured, skipping API server")

    # Start Telegram bot in background thread if configured
    if TELEGRAM_BOT_TOKEN and TELEGRAM_BOT_TOKEN != "xxx":
        bot_thread = threading.Thread(target=_run_telegram_bot, daemon=True)
        bot_thread.start()
        logger.info("Telegram bot started in background")
    else:
        logger.info("Telegram not configured, skipping bot")

    # Run scheduler in main event loop (blocking)
    asyncio.run(_run_scheduler())


if __name__ == "__main__":
    main()
