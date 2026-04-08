"""Post-ingest classification worker — runs in background with concurrency control."""

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from src.shared.config import WATCHER_PARALLEL_LIMIT
from src.shared.logger import get_logger

logger = get_logger("governance.auto_classify")

_executor = ThreadPoolExecutor(max_workers=WATCHER_PARALLEL_LIMIT, thread_name_prefix="classify")
_lock = threading.Lock()
_pending: set[str] = set()  # doc_ids currently being classified


def schedule_classify(doc_dir: Path, doc_id: str) -> None:
    """Submit a document for background classification. Non-blocking."""
    with _lock:
        if doc_id in _pending:
            logger.debug("Already queued: %s", doc_id[:8])
            return
        _pending.add(doc_id)

    try:
        _executor.submit(_classify_worker, doc_dir, doc_id)
        logger.info("Queued for classification: %s", doc_id[:8])
    except Exception as e:
        with _lock:
            _pending.discard(doc_id)
        logger.error("Failed to queue classification for %s: %s", doc_id[:8], e)


def _classify_worker(doc_dir: Path, doc_id: str) -> None:
    """Worker that classifies a single document."""
    try:
        if not doc_dir.exists():
            logger.warning("Document dir gone before classification: %s", doc_dir)
            return

        from src.governance.organizer import _process_entry
        result = _process_entry(doc_dir)

        if result:
            logger.info("Auto-classified: %s", doc_id[:8])

            # Notify via Telegram if configured
            try:
                from src.storage.db import get_document
                doc = get_document(doc_id)
                if doc:
                    title = doc.get("title", doc_id[:8])
                    category = doc.get("category", "?")

                    import asyncio
                    from src.scheduler.notifier import notify
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(notify(f"Classified: {title} → {category}"))
                    except RuntimeError:
                        asyncio.run(notify(f"Classified: {title} → {category}"))
            except Exception as e:
                logger.debug("Notification skipped: %s", e)
        else:
            logger.warning("Classification failed for: %s", doc_id[:8])
    except Exception as e:
        logger.error("Auto-classify error for %s: %s", doc_id[:8], e)
    finally:
        with _lock:
            _pending.discard(doc_id)
