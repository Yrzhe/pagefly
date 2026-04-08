"""Approval queue — Telegram inline keyboard approval for sensitive agent actions."""

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from src.shared.logger import get_logger

logger = get_logger("channels.approval")

APPROVAL_TIMEOUT = 300  # 5 minutes


@dataclass
class PendingAction:
    """A sensitive action awaiting user approval."""
    action_id: str
    tool_name: str
    doc_id: str
    title: str
    preview: str
    future: asyncio.Future = field(repr=False)
    created_at: float = field(default_factory=lambda: datetime.now(timezone.utc).timestamp())


# Global pending actions queue: action_id -> PendingAction
_pending: dict[str, PendingAction] = {}
_MAX_PENDING = 20  # Hard cap on concurrent pending approvals

# Callback to send approval message via Telegram (set by telegram.py on startup)
_send_approval_fn = None


def set_send_approval_callback(fn):
    """Register the Telegram send function. Called once at bot startup."""
    global _send_approval_fn
    _send_approval_fn = fn


async def request_approval(tool_name: str, doc_id: str, title: str, preview: str) -> bool:
    """
    Request user approval for a sensitive action.
    Blocks until user approves/rejects or timeout (auto-reject).
    Returns True if approved, False if rejected/timed out.
    """
    if _send_approval_fn is None:
        logger.warning("No approval callback registered, auto-approving")
        return True

    # Evict expired pending actions before adding new one
    now = datetime.now(timezone.utc).timestamp()
    expired = [aid for aid, a in _pending.items() if now - a.created_at > APPROVAL_TIMEOUT]
    for aid in expired:
        action = _pending.pop(aid)
        if not action.future.done():
            action.future.set_result(False)

    if len(_pending) >= _MAX_PENDING:
        logger.warning("Too many pending approvals (%d), rejecting", len(_pending))
        return False

    loop = asyncio.get_running_loop()
    future = loop.create_future()
    action_id = uuid.uuid4().hex[:12]

    action = PendingAction(
        action_id=action_id,
        tool_name=tool_name,
        doc_id=doc_id,
        title=title,
        preview=preview,
        future=future,
    )
    _pending[action_id] = action

    try:
        await _send_approval_fn(action)
    except Exception as e:
        logger.error("Failed to send approval request: %s", e)
        _pending.pop(action_id, None)
        return False

    try:
        result = await asyncio.wait_for(future, timeout=APPROVAL_TIMEOUT)
        return result
    except (asyncio.TimeoutError, asyncio.CancelledError):
        logger.info("Approval timed out / cancelled for %s (action=%s)", tool_name, action_id)
        return False
    finally:
        _pending.pop(action_id, None)


def resolve_action(action_id: str, approved: bool) -> bool:
    """Resolve a pending action. Returns False if action not found (expired/already resolved)."""
    action = _pending.pop(action_id, None)
    if action is None:
        return False

    if not action.future.done():
        action.future.set_result(approved)

    status = "approved" if approved else "rejected"
    logger.info("Action %s %s: %s on %s", action_id, status, action.tool_name, action.doc_id[:8])
    return True
