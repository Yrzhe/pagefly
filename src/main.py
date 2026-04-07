"""PageFly entry point — runs scheduler, watcher, and optionally Telegram bot."""

import asyncio
import sys
import threading

from src.shared.config import TELEGRAM_BOT_TOKEN
from src.shared.logger import get_logger
from src.storage.db import init_db

logger = get_logger("main")


def run_telegram_bot() -> None:
    """Run Telegram bot in a separate thread (it has its own event loop)."""
    from src.channels.telegram import run_bot
    try:
        run_bot()
    except Exception as e:
        logger.error("Telegram bot error: %s", e)


async def run_scheduler() -> None:
    """Run the unified scheduler + inbox watcher."""
    from src.scheduler.engine import start_scheduler
    await start_scheduler()


def main() -> None:
    """Start PageFly system."""
    init_db()
    logger.info("PageFly starting...")

    # Start Telegram bot in background thread if configured
    if TELEGRAM_BOT_TOKEN and TELEGRAM_BOT_TOKEN != "xxx":
        bot_thread = threading.Thread(target=run_telegram_bot, daemon=True)
        bot_thread.start()
        logger.info("Telegram bot started in background")
    else:
        logger.info("Telegram not configured, skipping bot")

    # Run scheduler in main event loop
    asyncio.run(run_scheduler())


if __name__ == "__main__":
    main()
