"""数据库连接和操作。"""

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
    created_at TEXT NOT NULL,
    FOREIGN KEY (document_id) REFERENCES documents(id)
);

CREATE TABLE IF NOT EXISTS wiki_articles (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    article_type TEXT NOT NULL,
    file_path TEXT NOT NULL,
    source_document_ids TEXT DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def get_connection() -> sqlite3.Connection:
    """获取数据库连接。"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """初始化数据库表。"""
    conn = get_connection()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()
    logger.info("Database initialized at %s", DB_PATH)


def now_iso() -> str:
    """当前时间 ISO 8601。"""
    return datetime.now(timezone.utc).astimezone().isoformat()


def insert_document(
    doc_id: str,
    source_type: str,
    original_filename: str,
    current_path: str,
    ingested_at: str,
) -> None:
    """插入新文档记录。"""
    conn = get_connection()
    conn.execute(
        """INSERT INTO documents (id, source_type, original_filename, current_path, ingested_at)
        VALUES (?, ?, ?, ?, ?)""",
        (doc_id, source_type, original_filename, current_path, ingested_at),
    )
    conn.commit()
    conn.close()


def update_document(doc_id: str, **fields) -> None:
    """更新文档字段。"""
    if not fields:
        return
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [doc_id]
    conn = get_connection()
    conn.execute(f"UPDATE documents SET {set_clause} WHERE id = ?", values)
    conn.commit()
    conn.close()


def get_document(doc_id: str) -> dict | None:
    """查询单个文档。"""
    conn = get_connection()
    row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def list_documents_by_status(status: str) -> list[dict]:
    """按状态查询文档列表。"""
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
    """写入操作日志。"""
    conn = get_connection()
    conn.execute(
        """INSERT INTO operations_log (document_id, operation, from_path, to_path, details_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?)""",
        (document_id, operation, from_path, to_path, details_json, now_iso()),
    )
    conn.commit()
    conn.close()
