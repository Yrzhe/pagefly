"""Database connection and operations."""

import sqlite3
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

from src.shared.config import DATA_DIR
from src.shared.logger import get_logger

logger = get_logger("storage.db")

DB_PATH = DATA_DIR / "pagefly.db"
_ALLOWED_DOC_COLUMNS = frozenset({
    "title",
    "description",
    "source_type",
    "original_filename",
    "current_path",
    "status",
    "tags",
    "category",
    "subcategory",
    "classified_at",
    "metadata_json",
})
_ALLOWED_WIKI_COLUMNS = frozenset({
    "title",
    "article_type",
    "file_path",
    "summary",
    "source_document_ids",
    "updated_at",
})
_ALLOWED_TASK_COLUMNS = frozenset({
    "name",
    "cron_expr",
    "prompt",
    "enabled",
    "task_type",
    "updated_at",
})

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    title TEXT DEFAULT '',
    description TEXT DEFAULT '',
    source_type TEXT NOT NULL,
    original_filename TEXT DEFAULT '',
    current_path TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'raw',
    tags TEXT DEFAULT '[]',
    category TEXT DEFAULT '',
    subcategory TEXT DEFAULT '',
    ingested_at TEXT NOT NULL,
    classified_at TEXT DEFAULT '',
    metadata_json TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS operations_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    from_path TEXT DEFAULT '',
    to_path TEXT DEFAULT '',
    details_json TEXT DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS wiki_articles (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    article_type TEXT NOT NULL,
    file_path TEXT NOT NULL,
    summary TEXT DEFAULT '',
    source_document_ids TEXT DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scheduled_tasks (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    cron_expr TEXT NOT NULL,
    task_type TEXT NOT NULL DEFAULT 'review',
    prompt TEXT DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS task_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT,
    task_name TEXT NOT NULL,
    task_type TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'user',
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    output TEXT DEFAULT '',
    error TEXT DEFAULT '',
    duration_ms INTEGER
);
CREATE INDEX IF NOT EXISTS idx_task_runs_task_id ON task_runs(task_id);
CREATE INDEX IF NOT EXISTS idx_task_runs_started_at ON task_runs(started_at DESC);

CREATE TABLE IF NOT EXISTS api_tokens (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    token_prefix TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    last_used_at TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS custom_prompts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    content TEXT NOT NULL,
    category TEXT DEFAULT 'general',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_sessions (
    chat_id INTEGER PRIMARY KEY,
    messages_json TEXT NOT NULL DEFAULT '[]',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audio_recordings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    local_uuid TEXT UNIQUE,
    device_id TEXT DEFAULT '',
    started_at TEXT NOT NULL,
    ended_at TEXT DEFAULT '',
    duration_s INTEGER DEFAULT 0,
    file_path TEXT NOT NULL,
    file_size_bytes INTEGER DEFAULT 0,
    format TEXT DEFAULT 'm4a',
    source TEXT DEFAULT 'mixed',
    trigger_app TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'uploaded',
    transcript TEXT DEFAULT '',
    transcript_path TEXT DEFAULT '',
    transcribed_at TEXT DEFAULT '',
    error TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audio_local_uuid ON audio_recordings(local_uuid);
CREATE INDEX IF NOT EXISTS idx_audio_started_at ON audio_recordings(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_audio_status ON audio_recordings(status);

CREATE TABLE IF NOT EXISTS activity_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    local_uuid TEXT UNIQUE,
    device_id TEXT DEFAULT '',
    started_at TEXT NOT NULL,
    ended_at TEXT DEFAULT '',
    duration_s INTEGER DEFAULT 0,
    app TEXT DEFAULT '',
    window_title TEXT DEFAULT '',
    url TEXT DEFAULT '',
    text_excerpt TEXT DEFAULT '',
    ax_role TEXT DEFAULT '',
    audio_id INTEGER REFERENCES audio_recordings(id) ON DELETE SET NULL,
    metadata_json TEXT DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_activity_local_uuid ON activity_events(local_uuid);
CREATE INDEX IF NOT EXISTS idx_activity_started_at ON activity_events(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_activity_audio_id ON activity_events(audio_id);
"""


def get_connection() -> sqlite3.Connection:
    """Get a database connection."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


from contextlib import contextmanager


@contextmanager
def transaction():
    """Context manager for atomic DB transactions.
    Usage: with db.transaction() as conn: conn.execute(...)
    Auto-commits on success, auto-rollbacks on exception."""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Initialize database tables and run migrations."""
    conn = get_connection()
    conn.executescript(SCHEMA)
    # Migration: add summary column if missing (for existing DBs)
    try:
        conn.execute("SELECT summary FROM wiki_articles LIMIT 1")
    except sqlite3.OperationalError:
        conn.execute("ALTER TABLE wiki_articles ADD COLUMN summary TEXT DEFAULT ''")
        logger.info("Migration: added summary column to wiki_articles")
    # Migration: api_tokens plaintext → hashed (rename token→token_hash, add token_prefix)
    try:
        conn.execute("SELECT token_hash FROM api_tokens LIMIT 1")
    except sqlite3.OperationalError:
        try:
            conn.execute("SELECT token FROM api_tokens LIMIT 1")
            # Old schema exists — migrate
            import hashlib
            rows = conn.execute("SELECT id, token FROM api_tokens").fetchall()
            conn.execute("ALTER TABLE api_tokens ADD COLUMN token_hash TEXT DEFAULT ''")
            conn.execute("ALTER TABLE api_tokens ADD COLUMN token_prefix TEXT DEFAULT ''")
            for row in rows:
                token_val = row["token"]
                h = hashlib.sha256(token_val.encode()).hexdigest()
                prefix = token_val[:8] + "..."
                conn.execute(
                    "UPDATE api_tokens SET token_hash = ?, token_prefix = ? WHERE id = ?",
                    (h, prefix, row["id"]),
                )
            # Clear plaintext tokens from old column
            conn.execute("UPDATE api_tokens SET token = '' WHERE token != ''")
            logger.info("Migration: hashed %d existing API tokens, cleared plaintext", len(rows))
        except sqlite3.OperationalError:
            pass  # Fresh DB, no migration needed
    # Migration: remove FK constraint from operations_log (allows document deletion)
    try:
        fk_info = conn.execute("PRAGMA foreign_key_list(operations_log)").fetchall()
        if fk_info:
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS operations_log_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    from_path TEXT DEFAULT '',
                    to_path TEXT DEFAULT '',
                    details_json TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                INSERT INTO operations_log_new SELECT * FROM operations_log;
                DROP TABLE operations_log;
                ALTER TABLE operations_log_new RENAME TO operations_log;
            """)
            conn.execute("PRAGMA foreign_keys=ON")
            logger.info("Migration: removed FK constraint from operations_log")
    except Exception as e:
        logger.warning("operations_log FK migration skipped: %s", e)
    conn.commit()
    conn.close()
    logger.info("Database initialized at %s", DB_PATH)


def now_iso() -> str:
    """Current time in ISO 8601."""
    return datetime.now(timezone.utc).astimezone().isoformat()


def _build_update_sql(table: str, allowed_columns: Iterable[str], fields: dict) -> tuple[str, list]:
    """Build a parameterized UPDATE statement after validating column names."""
    invalid = sorted(set(fields) - set(allowed_columns))
    if invalid:
        raise ValueError(f"Invalid {table} columns: {', '.join(invalid)}")

    set_clause = ", ".join(f"{column} = ?" for column in fields)
    return f"UPDATE {table} SET {set_clause} WHERE id = ?", list(fields.values())


def insert_document(
    doc_id: str,
    source_type: str,
    original_filename: str,
    current_path: str,
    ingested_at: str,
    title: str = "",
) -> None:
    """Insert a new document record."""
    conn = get_connection()
    conn.execute(
        """INSERT INTO documents (id, title, source_type, original_filename, current_path, ingested_at)
        VALUES (?, ?, ?, ?, ?, ?)""",
        (doc_id, title, source_type, original_filename, current_path, ingested_at),
    )
    conn.commit()
    conn.close()


def update_document(doc_id: str, **fields) -> None:
    """Update document fields by ID."""
    if not fields:
        return
    query, values = _build_update_sql("documents", _ALLOWED_DOC_COLUMNS, fields)
    conn = get_connection()
    try:
        conn.execute(query, [*values, doc_id])
        conn.commit()
    finally:
        conn.close()


def get_document(doc_id: str) -> dict | None:
    """Get a single document by ID."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def list_documents_by_status(status: str) -> list[dict]:
    """List documents by status."""
    conn = get_connection()
    rows = conn.execute("SELECT * FROM documents WHERE status = ?", (status,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def log_operation(
    document_id: str,
    operation: str,
    from_path: str = "",
    to_path: str = "",
    details_json: str = "{}",
) -> None:
    """Write an operation log entry."""
    conn = get_connection()
    conn.execute(
        """INSERT INTO operations_log (document_id, operation, from_path, to_path, details_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?)""",
        (document_id, operation, from_path, to_path, details_json, now_iso()),
    )
    conn.commit()
    conn.close()


# ── Wiki Articles ──

def list_wiki_articles_db() -> list[dict]:
    """List all wiki articles from database."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, title, article_type, file_path, summary, source_document_ids, created_at, updated_at "
        "FROM wiki_articles ORDER BY article_type, title"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_wiki_article(article_id: str, **fields) -> None:
    """Update wiki article fields by ID."""
    if not fields:
        return
    fields["updated_at"] = now_iso()
    query, values = _build_update_sql("wiki_articles", _ALLOWED_WIKI_COLUMNS, fields)
    conn = get_connection()
    try:
        conn.execute(query, [*values, article_id])
        conn.commit()
    finally:
        conn.close()


# ── Scheduled Tasks ──

def insert_scheduled_task(
    task_id: str, name: str, cron_expr: str,
    task_type: str = "review", prompt: str = "",
) -> None:
    """Insert a new scheduled task."""
    ts = now_iso()
    conn = get_connection()
    conn.execute(
        """INSERT INTO scheduled_tasks (id, name, cron_expr, task_type, prompt, enabled, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, 1, ?, ?)""",
        (task_id, name, cron_expr, task_type, prompt, ts, ts),
    )
    conn.commit()
    conn.close()


def update_scheduled_task(task_id: str, **fields) -> None:
    """Update scheduled task fields."""
    if not fields:
        return
    fields["updated_at"] = now_iso()
    query, values = _build_update_sql("scheduled_tasks", _ALLOWED_TASK_COLUMNS, fields)
    conn = get_connection()
    try:
        conn.execute(query, [*values, task_id])
        conn.commit()
    finally:
        conn.close()


def list_scheduled_tasks(enabled_only: bool = False) -> list[dict]:
    """List all scheduled tasks."""
    conn = get_connection()
    if enabled_only:
        rows = conn.execute("SELECT * FROM scheduled_tasks WHERE enabled = 1").fetchall()
    else:
        rows = conn.execute("SELECT * FROM scheduled_tasks").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_scheduled_task(task_id: str) -> None:
    """Delete a scheduled task."""
    conn = get_connection()
    conn.execute("DELETE FROM scheduled_tasks WHERE id = ?", (task_id,))
    conn.commit()
    conn.close()


# ── Task Runs (execution history) ──

def insert_task_run(
    task_id: str | None,
    task_name: str,
    task_type: str,
    source: str = "user",
) -> int:
    """Record the start of a task execution. Returns the run id."""
    conn = get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO task_runs (task_id, task_name, task_type, source, started_at, status)
               VALUES (?, ?, ?, ?, ?, 'running')""",
            (task_id, task_name, task_type, source, now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def finish_task_run(
    run_id: int,
    status: str,
    output: str = "",
    error: str = "",
    duration_ms: int = 0,
) -> None:
    """Update a task run with final status and output."""
    conn = get_connection()
    try:
        conn.execute(
            """UPDATE task_runs
               SET finished_at = ?, status = ?, output = ?, error = ?, duration_ms = ?
               WHERE id = ?""",
            (now_iso(), status, output, error, duration_ms, run_id),
        )
        conn.commit()
    finally:
        conn.close()


def list_task_runs(task_id: str | None = None, limit: int = 20) -> list[dict]:
    """List task runs, newest first. If task_id is None, returns recent runs across all tasks."""
    conn = get_connection()
    if task_id:
        rows = conn.execute(
            """SELECT id, task_id, task_name, task_type, source, started_at, finished_at,
                      status, duration_ms, substr(output, 1, 300) AS output_preview,
                      substr(error, 1, 300) AS error_preview
               FROM task_runs
               WHERE task_id = ?
               ORDER BY started_at DESC
               LIMIT ?""",
            (task_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT id, task_id, task_name, task_type, source, started_at, finished_at,
                      status, duration_ms, substr(output, 1, 300) AS output_preview,
                      substr(error, 1, 300) AS error_preview
               FROM task_runs
               ORDER BY started_at DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_task_run(run_id: int) -> dict | None:
    """Get a single task run with full output."""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM task_runs WHERE id = ?", (run_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


# ── Custom Prompts ──

def upsert_custom_prompt(prompt_id: str, name: str, content: str, category: str = "general") -> None:
    """Insert or update a custom prompt."""
    ts = now_iso()
    conn = get_connection()
    conn.execute(
        """INSERT INTO custom_prompts (id, name, content, category, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET content=?, category=?, updated_at=?""",
        (prompt_id, name, content, category, ts, ts, content, category, ts),
    )
    conn.commit()
    conn.close()


def get_custom_prompt(name: str) -> dict | None:
    """Get a custom prompt by name."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM custom_prompts WHERE name = ?", (name,)).fetchone()
    conn.close()
    return dict(row) if row else None


def list_custom_prompts(category: str | None = None) -> list[dict]:
    """List custom prompts, optionally filtered by category."""
    conn = get_connection()
    if category:
        rows = conn.execute("SELECT * FROM custom_prompts WHERE category = ?", (category,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM custom_prompts").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_custom_prompt(name: str) -> None:
    """Delete a custom prompt by name."""
    conn = get_connection()
    conn.execute("DELETE FROM custom_prompts WHERE name = ?", (name,))
    conn.commit()
    conn.close()


# ── API Tokens ──

def _hash_token(token: str) -> str:
    """SHA-256 hash a token for secure storage."""
    import hashlib
    return hashlib.sha256(token.encode()).hexdigest()


def insert_api_token(token_id: str, name: str, token: str) -> None:
    """Insert a new API token (stores hash, not plaintext)."""
    conn = get_connection()
    conn.execute(
        "INSERT INTO api_tokens (id, name, token_hash, token_prefix, created_at) VALUES (?, ?, ?, ?, ?)",
        (token_id, name, _hash_token(token), token[:8] + "...", now_iso()),
    )
    conn.commit()
    conn.close()


def validate_api_token(token: str) -> bool:
    """Check if a token exists by comparing hashes. Updates last_used_at."""
    token_hash = _hash_token(token)
    conn = get_connection()
    row = conn.execute("SELECT id FROM api_tokens WHERE token_hash = ?", (token_hash,)).fetchone()
    if row:
        conn.execute("UPDATE api_tokens SET last_used_at = ? WHERE token_hash = ?", (now_iso(), token_hash))
        conn.commit()
    conn.close()
    return row is not None


def list_api_tokens() -> list[dict]:
    """List all API tokens (shows prefix only, hash never exposed)."""
    conn = get_connection()
    rows = conn.execute("SELECT id, name, token_prefix, created_at, last_used_at FROM api_tokens").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_api_token(token_id: str) -> None:
    """Delete an API token by ID."""
    conn = get_connection()
    conn.execute("DELETE FROM api_tokens WHERE id = ?", (token_id,))
    conn.commit()
    conn.close()


# ── Chat Sessions ──

def save_session(chat_id: int, messages: list[dict]) -> None:
    """Persist a chat session to database."""
    import json
    conn = get_connection()
    conn.execute(
        """INSERT INTO chat_sessions (chat_id, messages_json, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(chat_id) DO UPDATE SET messages_json=excluded.messages_json, updated_at=excluded.updated_at""",
        (chat_id, json.dumps(messages, ensure_ascii=False), now_iso()),
    )
    conn.commit()
    conn.close()


def load_session(chat_id: int) -> list[dict] | None:
    """Load a chat session from database. Returns None if not found."""
    import json
    conn = get_connection()
    row = conn.execute("SELECT messages_json FROM chat_sessions WHERE chat_id = ?", (chat_id,)).fetchone()
    conn.close()
    if row:
        return json.loads(row["messages_json"])
    return None


def load_all_sessions() -> dict[int, list[dict]]:
    """Load all chat sessions from database."""
    import json
    conn = get_connection()
    rows = conn.execute("SELECT chat_id, messages_json FROM chat_sessions").fetchall()
    conn.close()
    return {row["chat_id"]: json.loads(row["messages_json"]) for row in rows}


def delete_session(chat_id: int) -> None:
    """Delete a chat session from database."""
    conn = get_connection()
    conn.execute("DELETE FROM chat_sessions WHERE chat_id = ?", (chat_id,))
    conn.commit()
    conn.close()


# ── Desktop Activity ──

def insert_audio_recording(
    local_uuid: str,
    started_at: str,
    ended_at: str,
    file_path: str,
    file_size_bytes: int = 0,
    duration_s: int = 0,
    fmt: str = "m4a",
    source: str = "mixed",
    trigger_app: str = "",
    device_id: str = "",
    status: str = "uploaded",
) -> int:
    """Idempotent insert keyed by local_uuid. Returns the server-side id."""
    ts = now_iso()
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO audio_recordings
               (local_uuid, device_id, started_at, ended_at, duration_s,
                file_path, file_size_bytes, format, source, trigger_app,
                status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(local_uuid) DO NOTHING""",
            (local_uuid, device_id, started_at, ended_at, duration_s,
             file_path, file_size_bytes, fmt, source, trigger_app,
             status, ts),
        )
        conn.commit()
        row = conn.execute(
            "SELECT id FROM audio_recordings WHERE local_uuid = ?", (local_uuid,)
        ).fetchone()
        return int(row["id"])
    finally:
        conn.close()


def get_audio_recording(audio_id: int) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM audio_recordings WHERE id = ?", (audio_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_audio_by_local_uuid(local_uuid: str) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM audio_recordings WHERE local_uuid = ?", (local_uuid,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def update_audio_transcript(
    audio_id: int,
    transcript: str,
    transcript_path: str = "",
    status: str = "transcribed",
    error: str = "",
) -> None:
    """Called by the STT worker once transcription finishes (or fails)."""
    conn = get_connection()
    try:
        conn.execute(
            """UPDATE audio_recordings
               SET transcript = ?, transcript_path = ?, status = ?,
                   transcribed_at = ?, error = ?
               WHERE id = ?""",
            (transcript, transcript_path, status, now_iso(), error, audio_id),
        )
        conn.commit()
    finally:
        conn.close()


def set_audio_status(audio_id: int, status: str, error: str = "") -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE audio_recordings SET status = ?, error = ? WHERE id = ?",
            (status, error, audio_id),
        )
        conn.commit()
    finally:
        conn.close()


def insert_activity_event(event: dict) -> int:
    """Idempotent insert of a single activity event, keyed by local_uuid.
    Returns the server-side row id."""
    ts = now_iso()
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO activity_events
               (local_uuid, device_id, started_at, ended_at, duration_s,
                app, window_title, url, text_excerpt, ax_role,
                audio_id, metadata_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(local_uuid) DO NOTHING""",
            (
                event["local_uuid"],
                event.get("device_id", ""),
                event["started_at"],
                event.get("ended_at", ""),
                int(event.get("duration_s", 0) or 0),
                event.get("app", ""),
                event.get("window_title", ""),
                event.get("url", ""),
                event.get("text_excerpt", ""),
                event.get("ax_role", ""),
                event.get("audio_id"),
                event.get("metadata_json", "{}"),
                ts,
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT id FROM activity_events WHERE local_uuid = ?",
            (event["local_uuid"],),
        ).fetchone()
        return int(row["id"])
    finally:
        conn.close()


def insert_activity_events_batch(events: list[dict]) -> dict[str, int]:
    """Bulk idempotent insert. Returns {local_uuid: server_id} for every row."""
    if not events:
        return {}
    ts = now_iso()
    conn = get_connection()
    try:
        conn.executemany(
            """INSERT INTO activity_events
               (local_uuid, device_id, started_at, ended_at, duration_s,
                app, window_title, url, text_excerpt, ax_role,
                audio_id, metadata_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(local_uuid) DO NOTHING""",
            [
                (
                    e["local_uuid"],
                    e.get("device_id", ""),
                    e["started_at"],
                    e.get("ended_at", ""),
                    int(e.get("duration_s", 0) or 0),
                    e.get("app", ""),
                    e.get("window_title", ""),
                    e.get("url", ""),
                    e.get("text_excerpt", ""),
                    e.get("ax_role", ""),
                    e.get("audio_id"),
                    e.get("metadata_json", "{}"),
                    ts,
                )
                for e in events
            ],
        )
        conn.commit()
        placeholders = ",".join(["?"] * len(events))
        rows = conn.execute(
            f"SELECT local_uuid, id FROM activity_events WHERE local_uuid IN ({placeholders})",
            [e["local_uuid"] for e in events],
        ).fetchall()
        return {r["local_uuid"]: int(r["id"]) for r in rows}
    finally:
        conn.close()


def list_activity_events(
    start: str | None = None,
    end: str | None = None,
    limit: int = 500,
) -> list[dict]:
    """List activity events in [start, end), newest first."""
    conn = get_connection()
    try:
        clauses: list[str] = []
        params: list = []
        if start:
            clauses.append("started_at >= ?")
            params.append(start)
        if end:
            clauses.append("started_at < ?")
            params.append(end)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(int(limit))
        rows = conn.execute(
            f"""SELECT * FROM activity_events
                {where}
                ORDER BY started_at DESC
                LIMIT ?""",
            params,
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def list_pending_transcriptions(limit: int = 10) -> list[dict]:
    """Audio rows waiting for (or retrying) transcription."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT * FROM audio_recordings
               WHERE status IN ('uploaded', 'transcribing')
               ORDER BY created_at ASC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
