"""Notification dispatcher — sends task results to configured channels."""

import asyncio

from src.shared.config import NOTIFY_TELEGRAM, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from src.shared.logger import get_logger

logger = get_logger("scheduler.notifier")


async def notify(message: str, file_path: str | None = None) -> None:
    """
    Send a notification to all configured channels.
    If Telegram is configured, sends message (and optional file) to the chat.
    """
    if NOTIFY_TELEGRAM and TELEGRAM_BOT_TOKEN and TELEGRAM_BOT_TOKEN != "xxx":
        await _notify_telegram(message, file_path)
    else:
        logger.info("Notification (no channel): %s", message[:200])


async def _notify_telegram(message: str, file_path: str | None = None) -> None:
    """Send notification to Telegram."""
    try:
        from telegram import Bot

        bot = Bot(token=TELEGRAM_BOT_TOKEN)

        # Telegram message limit
        if len(message) > 4000:
            chunks = [message[i:i+4000] for i in range(0, len(message), 4000)]
            for chunk in chunks:
                await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=chunk)
        else:
            await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)

        if file_path:
            from pathlib import Path
            p = Path(file_path)
            if p.exists():
                with open(p, "rb") as f:
                    await bot.send_document(chat_id=TELEGRAM_CHAT_ID, document=f, filename=p.name)

        logger.info("Telegram notification sent: %s", message[:100])

    except Exception as e:
        logger.error("Failed to send Telegram notification: %s", e)
