"""Inbox watcher — monitors inbox/ for new files, auto-ingests with concurrency limit."""

import asyncio
import shutil
from pathlib import Path

from src.ingest.pipeline import ingest
from src.scheduler.notifier import notify
from src.shared.config import WATCHER_INBOX_DIR, WATCHER_PARALLEL_LIMIT
from src.shared.logger import get_logger
from src.shared.types import IngestInput

logger = get_logger("scheduler.watcher")

_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    """Lazy-init semaphore for concurrency control."""
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(WATCHER_PARALLEL_LIMIT)
    return _semaphore


async def _process_file(file_path: Path) -> None:
    """Ingest a single file from inbox with concurrency limit."""
    async with _get_semaphore():
        try:
            logger.info("Processing inbox file: %s", file_path.name)

            input_data = IngestInput(
                type="file",
                file_path=str(file_path),
                original_filename=file_path.name,
            )

            # Run ingest in thread pool (it's sync)
            loop = asyncio.get_running_loop()
            doc_id = await loop.run_in_executor(None, ingest, input_data)

            if doc_id:
                # Move processed file out of inbox
                done_dir = WATCHER_INBOX_DIR / ".processed"
                done_dir.mkdir(exist_ok=True)
                shutil.move(str(file_path), str(done_dir / file_path.name))

                logger.info("Ingested from inbox: %s (id=%s)", file_path.name, doc_id[:8])
                await notify(f"New document ingested: {file_path.name} (id={doc_id[:8]})")
            else:
                logger.error("Failed to ingest: %s", file_path.name)

        except Exception as e:
            logger.error("Error processing %s: %s", file_path.name, e)


async def scan_inbox() -> int:
    """
    Scan inbox/ for new files and ingest them.
    Returns number of files processed.
    """
    WATCHER_INBOX_DIR.mkdir(parents=True, exist_ok=True)

    files = [
        f for f in sorted(WATCHER_INBOX_DIR.iterdir())
        if f.is_file() and not f.name.startswith(".")
    ]

    if not files:
        return 0

    logger.info("Found %d file(s) in inbox", len(files))

    tasks = [_process_file(f) for f in files]
    await asyncio.gather(*tasks)

    return len(files)


async def watch_inbox(poll_interval: int = 10) -> None:
    """
    Continuously watch inbox/ for new files.
    Uses polling with configurable interval (seconds).
    """
    logger.info("Inbox watcher started (dir=%s, parallel=%d, poll=%ds)",
                WATCHER_INBOX_DIR, WATCHER_PARALLEL_LIMIT, poll_interval)

    while True:
        try:
            await scan_inbox()
        except Exception as e:
            logger.error("Watcher error: %s", e)
        await asyncio.sleep(poll_interval)
