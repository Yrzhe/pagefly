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

# Compiler debounce: trigger once after a batch of classifications settle
_COMPILER_DEBOUNCE_SECS = 60
_compiler_timer: threading.Timer | None = None
_compiler_lock = threading.Lock()


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
            _schedule_compiler()

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


def _schedule_compiler() -> None:
    """Schedule a compiler run with debounce — resets timer on each call."""
    global _compiler_timer
    with _compiler_lock:
        if _compiler_timer is not None:
            _compiler_timer.cancel()
        _compiler_timer = threading.Timer(_COMPILER_DEBOUNCE_SECS, _trigger_compiler)
        _compiler_timer.daemon = True
        _compiler_timer.start()
        logger.info("Compiler scheduled (debounce %ds)", _COMPILER_DEBOUNCE_SECS)


def _trigger_compiler() -> None:
    """Actually run the compiler agent."""
    import asyncio
    logger.info("Triggering compiler after new classifications...")
    try:
        from src.agents.compiler import run_compiler
        # Try to use the running event loop (main thread), fall back to new loop
        try:
            loop = asyncio.get_running_loop()
            asyncio.run_coroutine_threadsafe(run_compiler(), loop)
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(run_compiler())
            finally:
                loop.close()
        logger.info("Compiler triggered successfully")
    except Exception as e:
        logger.error("Auto-compiler failed: %s", e)
