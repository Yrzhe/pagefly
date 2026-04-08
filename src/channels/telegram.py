"""Telegram bot — interactive channel for the Query Agent."""

import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from src.agents.base import file_send_queue
from src.agents.query import QuerySession, ask
from src.channels.approval import PendingAction, resolve_action, set_send_approval_callback
from src.shared.packaging import cleanup_temp_file
from src.shared.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, KNOWLEDGE_DIR
from src.shared.logger import get_logger
from src.storage.db import init_db

logger = get_logger("channels.telegram")

# Per-chat sessions for multi-turn conversations (with timestamps for TTL)
_sessions: dict[int, tuple[QuerySession, float]] = {}
_MAX_SESSIONS = 100
_SESSION_TTL = 86400  # 24 hours
_SESSION_MSG_CAP = 100  # Max messages per session (oldest trimmed)


def _get_session(chat_id: int) -> QuerySession:
    """Get or create a session for a chat. Loads from DB if not in memory."""
    now = datetime.now(timezone.utc).timestamp()

    # Evict expired sessions from memory
    expired = [cid for cid, (_, ts) in _sessions.items() if now - ts > _SESSION_TTL]
    for cid in expired:
        del _sessions[cid]

    # Evict oldest if over limit
    if len(_sessions) >= _MAX_SESSIONS and chat_id not in _sessions:
        oldest = min(_sessions, key=lambda k: _sessions[k][1])
        del _sessions[oldest]

    if chat_id not in _sessions:
        # Try to restore from database
        from src.storage.db import load_session
        saved = load_session(chat_id)
        session = QuerySession(messages=saved) if saved else QuerySession()
        _sessions[chat_id] = (session, now)
    else:
        # Update last access time
        session, _ = _sessions[chat_id]
        _sessions[chat_id] = (session, now)

    session = _sessions[chat_id][0]

    # Trim oldest messages if over cap
    if len(session.messages) > _SESSION_MSG_CAP:
        session.messages = session.messages[-_SESSION_MSG_CAP:]

    return session


def _persist_session(chat_id: int) -> None:
    """Save current session to database (call after each message exchange)."""
    if chat_id not in _sessions:
        return
    session, _ = _sessions[chat_id]
    if not session.messages:
        return
    from src.storage.db import save_session
    try:
        save_session(chat_id, session.messages)
    except Exception as e:
        logger.debug("Session persist failed: %s", e)


def _escape_md(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    special = r"_*[]()~`>#+-=|{}.!"
    return re.sub(f"([{re.escape(special)}])", r"\\\1", text)


def _format_response(text: str) -> str:
    """
    Convert agent response to Telegram MarkdownV2.
    Handles: bold, italic, code blocks, inline code, headers, lists.
    Tables are converted to plain lists.
    """
    lines = text.split("\n")
    result = []
    in_code_block = False

    for line in lines:
        # Code block toggle
        if line.strip().startswith("```"):
            in_code_block = not in_code_block
            result.append(line)
            continue

        if in_code_block:
            result.append(line)
            continue

        # Skip table separator lines
        if re.match(r"^\s*\|[-\s|:]+\|\s*$", line):
            continue

        # Convert table rows to plain text
        if line.strip().startswith("|") and line.strip().endswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            line = "  ".join(cells)

        # Convert headers to bold
        header_match = re.match(r"^(#{1,3})\s+(.*)", line)
        if header_match:
            header_text = _escape_md(header_match.group(2))
            result.append(f"*{header_text}*")
            continue

        # Convert **bold** — extract before escaping
        bold_parts = re.split(r"\*\*(.*?)\*\*", line)
        if len(bold_parts) > 1:
            formatted = ""
            for i, part in enumerate(bold_parts):
                if i % 2 == 0:
                    formatted += _escape_md(part)
                else:
                    formatted += f"*{_escape_md(part)}*"
            result.append(formatted)
            continue

        result.append(_escape_md(line))

    return "\n".join(result)


async def _post_init(app: Application) -> None:
    """Register bot commands so they show in the / menu."""
    commands = [
        BotCommand("start", "Show help"),
        BotCommand("search", "Search documents by keyword"),
        BotCommand("status", "Show knowledge base stats"),
        BotCommand("save", "Save conversation as memo"),
        BotCommand("reset", "Clear conversation context"),
    ]
    await app.bot.set_my_commands(commands)
    logger.info("Bot commands registered")


async def _cmd_start(update: Update, context) -> None:
    """Handle /start command."""
    text = (
        "*PageFly Knowledge OS*\n\n"
        "Send me a message to query your knowledge base\\.\n\n"
        "*Commands:*\n"
        "/search <keyword> \\— search documents\n"
        "/status \\— show knowledge base stats\n"
        "/reset \\— clear conversation context\n\n"
        "You can also upload PDF/text files to ingest them\\."
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)


async def _cmd_save(update: Update, context) -> None:
    """Handle /save command — save current conversation as a knowledge doc."""
    chat_id = update.effective_chat.id
    if TELEGRAM_CHAT_ID and str(chat_id) != str(TELEGRAM_CHAT_ID):
        return

    session = _get_session(chat_id)
    if not session.messages:
        await update.message.reply_text("No conversation to save.")
        return

    from src.ingest.metadata import generate_id, now_iso, write_metadata
    from src.storage import db
    from src.storage.files import create_file

    now = datetime.now(timezone.utc).astimezone()
    timestamp_str = now.strftime("%Y-%m-%d %H:%M")

    # Build content
    lines = []
    for msg in session.messages:
        role = "User" if msg["role"] == "user" else "PageFly"
        lines.append(f"**{role}**: {msg['content']}")

    # Extract title from first user message
    first_user = next((m["content"][:60] for m in session.messages if m["role"] == "user"), "Conversation")
    title = f"Memo: {first_user}"

    content = f"# {title}\n\n> Saved at {timestamp_str}\n\n" + "\n\n".join(lines)

    doc_id = generate_id()
    ts = now_iso()
    folder_name = f"memo_{now.strftime('%Y%m%d_%H%M')}_{doc_id[:8]}"
    doc_dir = KNOWLEDGE_DIR / "notes" / folder_name

    try:
        create_file(doc_dir / "document.md", content)
        metadata = {
            "id": doc_id,
            "title": title,
            "description": f"Conversation memo saved at {timestamp_str}",
            "source_type": "conversation",
            "original_filename": "",
            "ingested_at": ts,
            "status": "classified",
            "location": f"knowledge/notes/{folder_name}",
            "tags": ["memo", "conversation"],
            "category": "notes",
            "subcategory": "",
            "references": [],
        }
        write_metadata(doc_dir, metadata)

        with db.transaction() as conn:
            conn.execute(
                """INSERT INTO documents (id, title, source_type, original_filename, current_path, ingested_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (doc_id, title, "conversation", "", str(doc_dir), ts),
            )
            conn.execute(
                "UPDATE documents SET status=?, category=? WHERE id=?",
                ("classified", "notes", doc_id),
            )
            conn.execute(
                """INSERT INTO operations_log (document_id, operation, from_path, to_path, details_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (doc_id, "ingest", "", str(doc_dir), "{}", ts),
            )
    except Exception as e:
        import shutil
        if doc_dir.exists():
            shutil.rmtree(doc_dir, ignore_errors=True)
        logger.error("Failed to save memo: %s", e)
        await update.message.reply_text(f"Error saving memo: {e}")
        return

    await update.message.reply_text(
        f"Saved {len(session.messages)} messages as memo\nID: {doc_id[:8]}"
    )
    logger.info("Conversation saved as memo: %s (%d messages)", title[:40], len(session.messages))


async def _cmd_reset(update: Update, context) -> None:
    """Handle /reset command."""
    chat_id = update.effective_chat.id
    _sessions[chat_id] = (QuerySession(), datetime.now(timezone.utc).timestamp())
    from src.storage.db import delete_session
    delete_session(chat_id)
    await update.message.reply_text("Conversation context cleared\\.", parse_mode=ParseMode.MARKDOWN_V2)


async def _cmd_status(update: Update, context) -> None:
    """Handle /status command."""
    from src.storage.db import get_connection

    conn = get_connection()
    doc_count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    wiki_count = conn.execute("SELECT COUNT(*) FROM wiki_articles").fetchone()[0]
    ops_count = conn.execute("SELECT COUNT(*) FROM operations_log").fetchone()[0]
    conn.close()

    text = (
        f"*Knowledge Base Stats*\n\n"
        f"Documents: {doc_count}\n"
        f"Wiki articles: {wiki_count}\n"
        f"Operations logged: {ops_count}"
    )
    await update.message.reply_text(_escape_md(text).replace(r"\*", "*"), parse_mode=ParseMode.MARKDOWN_V2)


async def _cmd_search(update: Update, context) -> None:
    """Handle /search <keyword> command."""
    if not context.args:
        await update.message.reply_text("Usage: /search <keyword>")
        return

    keyword = " ".join(context.args).lower()
    wiki_dir = KNOWLEDGE_DIR.parent / "wiki"

    results = []
    for root_dir, doc_type in ((KNOWLEDGE_DIR, "knowledge"), (wiki_dir, "wiki")):
        if not root_dir.exists():
            continue
        for md_path in root_dir.rglob("document.md"):
            content = md_path.read_text(encoding="utf-8")
            if keyword not in content.lower():
                continue
            meta_path = md_path.parent / "metadata.json"
            title = md_path.parent.name
            if meta_path.exists():
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                title = meta.get("title", title)
            results.append(f"[{doc_type}] {title}")

    if results:
        lines = "\n".join(f"  {r}" for r in results[:10])
        text = f"Found {len(results)} result(s):\n{lines}"
    else:
        text = f"No results for '{keyword}'"

    await update.message.reply_text(text)


async def _keep_typing(chat, stop_event: asyncio.Event) -> None:
    """Send typing action every 4 seconds until stop_event is set."""
    while not stop_event.is_set():
        try:
            await chat.send_action("typing")
        except Exception:
            pass
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=4)
        except asyncio.TimeoutError:
            pass


# Friendly names for tool display
_TOOL_LABELS = {
    "list_knowledge_docs": "Listing documents",
    "read_document": "Reading document",
    "search_documents": "Searching",
    "write_wiki_article": "Writing wiki article",
    "list_wiki_articles": "Listing wiki articles",
    "update_document_content": "Updating document",
    "create_knowledge_doc": "Creating document",
}


async def _handle_message(update: Update, context) -> None:
    """Handle regular text messages — send to query agent."""
    chat_id = update.effective_chat.id
    user_message = update.message.text

    if TELEGRAM_CHAT_ID and str(chat_id) != str(TELEGRAM_CHAT_ID):
        logger.warning("Unauthorized chat: %d", chat_id)
        return

    session = _get_session(chat_id)
    logger.info("User message: %s", user_message[:100])

    # Send status message and start typing indicator
    status_msg = await update.message.reply_text("Thinking...")
    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(_keep_typing(update.message.chat, stop_typing))

    try:
        # Callback to update status message with current tool
        async def on_tool_call(tool_name: str):
            label = _TOOL_LABELS.get(tool_name, tool_name)
            try:
                await status_msg.edit_text(f"{label}...")
            except Exception:
                pass

        response = await ask(user_message, session, on_tool_call=on_tool_call)

        # Stop typing indicator
        stop_typing.set()
        await typing_task

        # Delete status message
        try:
            await status_msg.delete()
        except Exception:
            pass

        # Send formatted response
        formatted = _format_response(response)

        if len(formatted) > 4000:
            chunks = [formatted[i:i+4000] for i in range(0, len(formatted), 4000)]
            for chunk in chunks:
                try:
                    await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN_V2)
                except Exception:
                    await update.message.reply_text(response[:4000])
        else:
            try:
                await update.message.reply_text(formatted, parse_mode=ParseMode.MARKDOWN_V2)
            except Exception:
                await update.message.reply_text(response)

        # Send any queued files
        while not file_send_queue.empty():
            file_path = await file_send_queue.get()
            try:
                with open(file_path, "rb") as f:
                    await update.message.reply_document(
                        document=f,
                        filename=file_path.name,
                    )
                logger.info("Sent file: %s", file_path.name)
            except Exception as e:
                logger.error("Failed to send file %s: %s", file_path, e)
            finally:
                cleanup_temp_file(file_path)

        # Persist session to DB after successful exchange
        _persist_session(chat_id)

    except Exception as e:
        stop_typing.set()
        await typing_task
        logger.error("Agent error: %s", e)
        try:
            await status_msg.edit_text(f"Error: {e}")
        except Exception:
            await update.message.reply_text(f"Error: {e}")


async def _handle_document(update: Update, context) -> None:
    """Handle document uploads — ingest into raw/."""
    chat_id = update.effective_chat.id
    if TELEGRAM_CHAT_ID and str(chat_id) != str(TELEGRAM_CHAT_ID):
        return

    doc = update.message.document
    if not doc:
        return

    filename = doc.file_name or "unnamed"
    await update.message.reply_text(f"Received: {filename}\nProcessing...")

    tmp_path = _safe_tmp_path(filename)
    try:
        file = await context.bot.get_file(doc.file_id)
        await file.download_to_drive(str(tmp_path))

        doc_id = _ingest_file(str(tmp_path), filename)
        if doc_id:
            await update.message.reply_text(f"Ingested: {filename}\nDocument ID: {doc_id[:8]}")
        else:
            await update.message.reply_text(f"Failed to ingest: {filename}")
    except Exception as e:
        logger.error("Document ingest error: %s", e)
        await update.message.reply_text(f"Error processing document: {e}")
    finally:
        _cleanup_tmp(tmp_path)


async def _handle_photo(update: Update, context) -> None:
    """Handle photo messages — ingest via image converter."""
    chat_id = update.effective_chat.id
    if TELEGRAM_CHAT_ID and str(chat_id) != str(TELEGRAM_CHAT_ID):
        return

    photos = update.message.photo
    if not photos:
        return

    # Get the largest photo (last in the list)
    photo = photos[-1]
    filename = f"photo_{photo.file_unique_id}.jpg"
    await update.message.reply_text("Processing photo...")

    tmp_path = _safe_tmp_path(filename)
    try:
        file = await context.bot.get_file(photo.file_id)
        await file.download_to_drive(str(tmp_path))

        doc_id = _ingest_file(str(tmp_path), filename)
        if doc_id:
            await update.message.reply_text(f"Ingested photo: {doc_id[:8]}")
        else:
            await update.message.reply_text("Failed to ingest photo")
    except Exception as e:
        logger.error("Photo ingest error: %s", e)
        await update.message.reply_text(f"Error processing photo: {e}")
    finally:
        _cleanup_tmp(tmp_path)


async def _handle_voice(update: Update, context) -> None:
    """Handle voice messages — ingest via voice converter."""
    chat_id = update.effective_chat.id
    if TELEGRAM_CHAT_ID and str(chat_id) != str(TELEGRAM_CHAT_ID):
        return

    voice = update.message.voice
    if not voice:
        return

    filename = f"voice_{voice.file_unique_id}.ogg"
    await update.message.reply_text("Transcribing voice message...")

    tmp_path = _safe_tmp_path(filename)
    try:
        file = await context.bot.get_file(voice.file_id)
        await file.download_to_drive(str(tmp_path))

        doc_id = _ingest_file(str(tmp_path), filename)
        if doc_id:
            await update.message.reply_text(f"Voice transcribed and ingested: {doc_id[:8]}")
        else:
            await update.message.reply_text("Failed to transcribe voice message")
    except Exception as e:
        logger.error("Voice ingest error: %s", e)
        await update.message.reply_text(f"Error processing voice: {e}")
    finally:
        _cleanup_tmp(tmp_path)


async def _handle_audio(update: Update, context) -> None:
    """Handle audio file messages — ingest via voice converter."""
    chat_id = update.effective_chat.id
    if TELEGRAM_CHAT_ID and str(chat_id) != str(TELEGRAM_CHAT_ID):
        return

    audio = update.message.audio
    if not audio:
        return

    filename = audio.file_name or f"audio_{audio.file_unique_id}.mp3"
    await update.message.reply_text(f"Transcribing: {filename}...")

    tmp_path = _safe_tmp_path(filename)
    try:
        file = await context.bot.get_file(audio.file_id)
        await file.download_to_drive(str(tmp_path))

        doc_id = _ingest_file(str(tmp_path), filename)
        if doc_id:
            await update.message.reply_text(f"Audio transcribed and ingested: {doc_id[:8]}")
        else:
            await update.message.reply_text(f"Failed to transcribe: {filename}")
    except Exception as e:
        logger.error("Audio ingest error: %s", e)
        await update.message.reply_text(f"Error processing audio: {e}")
    finally:
        _cleanup_tmp(tmp_path)


async def _handle_video(update: Update, context) -> None:
    """Handle video messages — download and ingest (audio track transcription)."""
    chat_id = update.effective_chat.id
    if TELEGRAM_CHAT_ID and str(chat_id) != str(TELEGRAM_CHAT_ID):
        return

    video = update.message.video or update.message.video_note
    if not video:
        return

    filename = getattr(video, "file_name", None) or f"video_{video.file_unique_id}.mp4"
    await update.message.reply_text(f"Processing video: {filename}...")

    tmp_path = _safe_tmp_path(filename)
    try:
        file = await context.bot.get_file(video.file_id)
        await file.download_to_drive(str(tmp_path))

        doc_id = _ingest_file(str(tmp_path), filename)
        if doc_id:
            await update.message.reply_text(f"Video ingested: {doc_id[:8]}")
        else:
            await update.message.reply_text(f"Failed to process video: {filename}")
    except Exception as e:
        logger.error("Video ingest error: %s", e)
        await update.message.reply_text(f"Error processing video: {e}")
    finally:
        _cleanup_tmp(tmp_path)


def _safe_tmp_path(filename: str) -> Path:
    """Create a safe temp path — strip path traversal from filename."""
    import tempfile
    safe_name = re.sub(r'[^\w\-.]', '_', Path(filename).name) or "upload"
    tmp_dir = Path(tempfile.mkdtemp(prefix="pagefly_"))
    return tmp_dir / safe_name


def _ingest_file(file_path: str, original_filename: str) -> str | None:
    """Common ingest logic for all media types."""
    from src.ingest.pipeline import ingest
    from src.shared.types import IngestInput

    input_data = IngestInput(
        type="file",
        file_path=file_path,
        original_filename=original_filename,
    )
    return ingest(input_data)


def _cleanup_tmp(tmp_path: Path) -> None:
    """Clean up temp file and its parent dir."""
    try:
        tmp_path.unlink(missing_ok=True)
        parent = tmp_path.parent
        if parent.exists() and parent.name.startswith("pagefly_") and not any(parent.iterdir()):
            parent.rmdir()
    except Exception:
        pass


async def _save_daily_chat(context) -> None:
    """Scheduled job: archive today's chat as a knowledge document."""
    from src.ingest.metadata import generate_id, now_iso, write_metadata
    from src.storage import db
    from src.storage.files import create_file

    now = datetime.now(timezone.utc).astimezone()
    today = now.strftime("%Y-%m-%d")
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()

    for chat_id, (session, _ts) in list(_sessions.items()):
        if not session.messages:
            continue

        # Only archive today's messages (avoid re-archiving old ones)
        today_msgs = [
            m for m in session.messages
            if m.get("ts", "") >= today_start
        ]

        if not today_msgs:
            continue

        lines = []
        for msg in today_msgs:
            role = "User" if msg["role"] == "user" else "PageFly"
            lines.append(f"**{role}**: {msg['content']}")

        content = f"# Chat Log — {today}\n\n" + "\n\n".join(lines)

        doc_id = generate_id()
        timestamp = now_iso()
        folder_name = f"chat_{today}_{doc_id[:8]}"
        doc_dir = KNOWLEDGE_DIR / "conversations" / folder_name

        try:
            create_file(doc_dir / "document.md", content)
            metadata = {
                "id": doc_id,
                "title": f"Chat Log {today}",
                "description": f"Daily conversation log from {today}",
                "source_type": "conversation",
                "original_filename": "",
                "ingested_at": timestamp,
                "status": "classified",
                "location": f"knowledge/conversations/{folder_name}",
                "tags": ["chat", "daily"],
                "category": "conversations",
                "subcategory": "",
                "references": [],
            }
            write_metadata(doc_dir, metadata)

            with db.transaction() as conn:
                conn.execute(
                    """INSERT INTO documents (id, title, source_type, original_filename, current_path, ingested_at)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    (doc_id, f"Chat Log {today}", "conversation", "", str(doc_dir), timestamp),
                )
                conn.execute(
                    "UPDATE documents SET status=?, category=? WHERE id=?",
                    ("classified", "conversations", doc_id),
                )
                conn.execute(
                    """INSERT INTO operations_log (document_id, operation, from_path, to_path, details_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    (doc_id, "ingest", "", str(doc_dir), "{}", timestamp),
                )
        except Exception as e:
            import shutil
            if doc_dir.exists():
                shutil.rmtree(doc_dir, ignore_errors=True)
            logger.error("Failed to save daily chat for %s: %s", chat_id, e)
            continue

        logger.info("Saved daily chat log: %s (%d messages, %d today)", today, len(session.messages), len(today_msgs))

        # Trim to last 50 messages (keep context for tomorrow) instead of clearing
        session.messages = session.messages[-50:]
        # Refresh timestamp so session doesn't expire before next use
        _sessions[chat_id] = (session, datetime.now(timezone.utc).timestamp())


# ── Approval flow (inline keyboard) ──

# Reference to the bot Application, set in run_bot()
_app: Application | None = None


async def _send_approval_to_telegram(action: PendingAction) -> None:
    """Send an approval request with inline keyboard to the configured chat."""
    if _app is None or not TELEGRAM_CHAT_ID:
        logger.error("Cannot send approval: bot not initialized or no chat_id")
        return

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Approve", callback_data=f"approve:{action.action_id}"),
            InlineKeyboardButton("Reject", callback_data=f"reject:{action.action_id}"),
        ]
    ])

    text = (
        f"*Approval Required*\n\n"
        f"Tool: `{action.tool_name}`\n"
        f"Document: {_escape_md(action.title)} \\(`{action.doc_id[:8]}`\\)\n\n"
        f"*Preview:*\n{_escape_md(action.preview)}"
    )

    # Truncate if too long
    if len(text) > 4000:
        text = text[:3950] + "\n\\.\\.\\. \\(truncated\\)"

    await _app.bot.send_message(
        chat_id=int(TELEGRAM_CHAT_ID),
        text=text,
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=keyboard,
    )


async def _handle_callback(update: Update, context) -> None:
    """Handle inline keyboard callback for approval/rejection."""
    query = update.callback_query
    await query.answer()

    data = query.data or ""
    if ":" not in data:
        return

    decision, action_id = data.split(":", 1)
    if decision not in ("approve", "reject"):
        return
    approved = decision == "approve"

    if resolve_action(action_id, approved):
        status_emoji = "Approved" if approved else "Rejected"
        await query.edit_message_reply_markup(reply_markup=None)
        await query.edit_message_text(
            text=query.message.text + f"\n\n— {status_emoji}",
        )
    else:
        await query.edit_message_reply_markup(reply_markup=None)
        await query.edit_message_text(
            text=query.message.text + "\n\n— Expired",
        )


def run_bot() -> None:
    """Start the Telegram bot."""
    global _app

    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "xxx":
        raise ValueError("TELEGRAM_BOT_TOKEN not configured in config.json")

    init_db()
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    _app = app

    # Register approval callback so agents can request approval via Telegram
    set_send_approval_callback(_send_approval_to_telegram)

    # Register commands on startup
    app.post_init = _post_init

    # Command handlers
    app.add_handler(CommandHandler("start", _cmd_start))
    app.add_handler(CommandHandler("save", _cmd_save))
    app.add_handler(CommandHandler("reset", _cmd_reset))
    app.add_handler(CommandHandler("status", _cmd_status))
    app.add_handler(CommandHandler("search", _cmd_search))

    # Inline keyboard callbacks (approval flow)
    app.add_handler(CallbackQueryHandler(_handle_callback))

    # Document uploads
    app.add_handler(MessageHandler(filters.Document.ALL, _handle_document))
    app.add_handler(MessageHandler(filters.PHOTO, _handle_photo))
    app.add_handler(MessageHandler(filters.VOICE, _handle_voice))
    app.add_handler(MessageHandler(filters.AUDIO, _handle_audio))
    app.add_handler(MessageHandler(filters.VIDEO | filters.VIDEO_NOTE, _handle_video))

    # Text messages (must be last — catch-all)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _handle_message))

    # Daily chat archive job at 23:55
    job_queue = app.job_queue
    if job_queue:
        job_queue.run_daily(
            _save_daily_chat,
            time=datetime.strptime("23:55", "%H:%M").time(),
            name="daily_chat_archive",
        )
        logger.info("Daily chat archive job scheduled at 23:55")

    logger.info("Telegram bot starting...")
    app.run_polling(drop_pending_updates=True)


async def start_bot() -> Application:
    """Initialize and start the Telegram bot (non-blocking, for integration with other async services)."""
    global _app

    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "xxx":
        raise ValueError("TELEGRAM_BOT_TOKEN not configured in config.json")

    init_db()
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    _app = app

    set_send_approval_callback(_send_approval_to_telegram)
    app.post_init = _post_init

    app.add_handler(CommandHandler("start", _cmd_start))
    app.add_handler(CommandHandler("save", _cmd_save))
    app.add_handler(CommandHandler("reset", _cmd_reset))
    app.add_handler(CommandHandler("status", _cmd_status))
    app.add_handler(CommandHandler("search", _cmd_search))
    app.add_handler(CallbackQueryHandler(_handle_callback))
    app.add_handler(MessageHandler(filters.Document.ALL, _handle_document))
    app.add_handler(MessageHandler(filters.PHOTO, _handle_photo))
    app.add_handler(MessageHandler(filters.VOICE, _handle_voice))
    app.add_handler(MessageHandler(filters.AUDIO, _handle_audio))
    app.add_handler(MessageHandler(filters.VIDEO | filters.VIDEO_NOTE, _handle_video))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _handle_message))

    job_queue = app.job_queue
    if job_queue:
        job_queue.run_daily(
            _save_daily_chat,
            time=datetime.strptime("23:55", "%H:%M").time(),
            name="daily_chat_archive",
        )
        logger.info("Daily chat archive job scheduled at 23:55")

    await app.initialize()
    await app.start()

    # Register bot commands (post_init doesn't fire in manual start mode)
    await _post_init(app)

    await app.updater.start_polling(drop_pending_updates=True)
    logger.info("Telegram bot started (async)")
    return app


async def stop_bot() -> None:
    """Stop the Telegram bot gracefully."""
    if _app is None:
        return
    await _app.updater.stop()
    await _app.stop()
    await _app.shutdown()
    logger.info("Telegram bot stopped")


if __name__ == "__main__":
    run_bot()
