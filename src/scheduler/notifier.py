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
    """Send notification to Telegram with MarkdownV2 formatting."""
    try:
        from telegram import Bot
        from telegram.constants import ParseMode
        from src.channels.telegram import _format_response

        bot = Bot(token=TELEGRAM_BOT_TOKEN)

        async def _send(text: str):
            formatted = _format_response(text)
            try:
                await bot.send_message(
                    chat_id=TELEGRAM_CHAT_ID,
                    text=formatted,
                    parse_mode=ParseMode.MARKDOWN_V2,
                )
            except Exception:
                # Fallback to plain text if formatting fails
                await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=text)

        if len(message) > 4000:
            chunks = [message[i:i+4000] for i in range(0, len(message), 4000)]
            for chunk in chunks:
                await _send(chunk)
        else:
            await _send(message)

        if file_path:
            from pathlib import Path
            p = Path(file_path)
            if p.exists():
                with open(p, "rb") as f:
                    await bot.send_document(chat_id=TELEGRAM_CHAT_ID, document=f, filename=p.name)

        logger.info("Telegram notification sent: %s", message[:100])

    except Exception as e:
        logger.error("Failed to send Telegram notification: %s", e)
