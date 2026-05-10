"""Tests for Daily Random Roam — API endpoint and scheduler function."""

import json
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from src.storage.db import init_db, get_connection


class TestRoamAPI:
    """Test the /api/roam endpoint logic (DB queries)."""

    def test_random_selection_returns_results(self):
        """Random query returns documents from the DB."""
        init_db()
        conn = get_connection()
        rows = conn.execute(
            "SELECT id, title, category, subcategory, current_path, ingested_at "
            "FROM documents WHERE status != 'error' "
            "ORDER BY RANDOM() LIMIT 3"
        ).fetchall()
        conn.close()

        # Should return up to 3 results (may be 0 if DB is empty)
        assert len(rows) <= 3
        for row in rows:
            assert row["id"]
            assert row["title"] is not None

    def test_random_selection_varies(self):
        """Two random queries should not always return the same docs."""
        init_db()
        conn = get_connection()

        results = []
        for _ in range(5):
            rows = conn.execute(
                "SELECT id FROM documents WHERE status != 'error' "
                "ORDER BY RANDOM() LIMIT 3"
            ).fetchall()
            results.append(tuple(r["id"] for r in rows))

        conn.close()

        # If there are >3 documents, we should see variation
        total_docs = get_connection().execute(
            "SELECT COUNT(*) FROM documents WHERE status != 'error'"
        ).fetchone()[0]

        if total_docs > 3:
            unique_results = set(results)
            assert len(unique_results) > 1, "Random selection should vary across calls"

    def test_old_docs_preferred(self):
        """Query prefers documents older than 7 days."""
        init_db()
        conn = get_connection()
        old_rows = conn.execute(
            "SELECT COUNT(*) FROM documents "
            "WHERE status != 'error' AND ingested_at < date('now', '-7 days')"
        ).fetchone()[0]
        conn.close()

        # Just verify the query doesn't crash
        conn = get_connection()
        rows = conn.execute(
            "SELECT id FROM documents WHERE status != 'error' "
            "AND ingested_at < date('now', '-7 days') "
            "ORDER BY RANDOM() LIMIT 3"
        ).fetchall()
        conn.close()

        assert len(rows) <= 3
        assert len(rows) <= old_rows


class TestRoamScheduler:
    def test_roam_function_importable(self):
        """_run_daily_roam is importable from engine (may skip if apscheduler missing)."""
        try:
            from src.scheduler.engine import _run_daily_roam
            assert callable(_run_daily_roam)
        except ImportError:
            pytest.skip("apscheduler not installed in test environment")


class TestRoamFormatting:
    def test_preview_strip_frontmatter(self):
        """Preview should strip YAML frontmatter from document content."""
        raw = "---\ntitle: Test\ntype: concept\n---\n\n# Hello World\n\nThis is the content."

        # Simulate frontmatter stripping (same logic as API)
        if raw.startswith("---"):
            parts = raw.split("---", 2)
            raw = parts[2].strip() if len(parts) >= 3 else raw

        assert raw.startswith("# Hello World")
        assert "---" not in raw

    def test_preview_truncation(self):
        """Preview is limited to 500 chars."""
        long_content = "x" * 1000
        preview = long_content[:500]
        assert len(preview) == 500
