"""Database connection and operations."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from src.shared.config import DATA_DIR
from src.shared.logger import get_logger

logger = get_logger("storage.db")

DB_PATH = DATA_DIR / "pagefly.db"

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
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [doc_id]
    conn = get_connection()
    conn.execute(f"UPDATE documents SET {set_clause} WHERE id = ?", values)
    conn.commit()
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
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [article_id]
    conn = get_connection()
    conn.execute(f"UPDATE wiki_articles SET {set_clause} WHERE id = ?", values)
    conn.commit()
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
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [task_id]
    conn = get_connection()
    conn.execute(f"UPDATE scheduled_tasks SET {set_clause} WHERE id = ?", values)
    conn.commit()
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
