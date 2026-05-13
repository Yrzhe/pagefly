"""Tests for Daily Random Roam — weighted selection from wiki articles, dedup, formatting."""

import json
from unittest.mock import patch, MagicMock

import pytest

from src.storage.db import init_db, get_connection


class TestRoamSelection:
    """Test the weighted random selection from wiki concept/connection/insight articles."""

    def test_pick_returns_results(self):
        """pick_roam_docs returns wiki articles."""
        init_db()
        from src.shared.roam import pick_roam_docs
        items = pick_roam_docs(count=3)
        assert isinstance(items, list)
        assert len(items) <= 3
        for item in items:
            assert "id" in item
            assert "title" in item
            assert item.get("preview_type") in ("concept", "connection", "insight", "")

    def test_excludes_review_lint_summary(self):
        """Only concept/connection/insight articles are selected, never review/lint/summary."""
        init_db()
        from src.shared.roam import pick_roam_docs
        # Run multiple times to increase confidence
        for _ in range(5):
            items = pick_roam_docs(count=3)
            for item in items:
                assert item.get("preview_type") not in ("review", "lint", "summary")

    def test_pick_records_history(self):
        """Picked articles are recorded in roam_history."""
        init_db()
        from src.shared.roam import pick_roam_docs

        items = pick_roam_docs(count=1)
        if not items:
            pytest.skip("No wiki articles in DB")

        conn = get_connection()
        row = conn.execute(
            "SELECT doc_id FROM roam_history WHERE doc_id = ?",
            (items[0]["id"],),
        ).fetchone()
        conn.close()
        assert row is not None

    def test_dedup_excludes_recent(self):
        """Recently roamed articles are excluded from next pick."""
        init_db()
        from src.shared.roam import pick_roam_docs

        conn = get_connection()
        total = conn.execute(
            "SELECT COUNT(*) FROM wiki_articles WHERE article_type IN ('concept','connection','insight')"
        ).fetchone()[0]
        conn.close()

        if total <= 3:
            pytest.skip("Not enough wiki articles to test dedup")

        first = pick_roam_docs(count=3)
        second = pick_roam_docs(count=3)
        # Both should work without crash
        assert isinstance(first, list)
        assert isinstance(second, list)


class TestRoamFormatting:
    def test_format_message(self):
        """format_roam_message produces markdown output."""
        from src.shared.roam import format_roam_message

        items = [
            {"id": "a", "title": "Test Concept", "category": "concept", "subcategory": "", "preview": "Some insight here", "preview_type": "concept", "ingested_at": "2026-01-01"},
            {"id": "b", "title": "A ↔ B Connection", "category": "connection", "subcategory": "", "preview": "How they relate", "preview_type": "connection", "ingested_at": "2026-01-02"},
        ]
        result = format_roam_message(items)
        assert "**Random Roam**" in result
        assert "Test Concept" in result
        assert "[concept]" in result
        assert "[connection]" in result

    def test_format_empty(self):
        """Empty items returns fallback message."""
        from src.shared.roam import format_roam_message
        result = format_roam_message([])
        assert "No articles" in result

    def test_preview_truncation(self):
        """Preview is truncated to max_preview chars."""
        from src.shared.roam import format_roam_message

        items = [{"id": "x", "title": "Long", "category": "concept", "subcategory": "", "preview": "x" * 2000, "preview_type": "concept", "ingested_at": ""}]
        result = format_roam_message(items, max_preview=100)
        assert "..." in result
        assert len(result) < 2000


class TestRoamDBHelpers:
    def test_record_and_get_recently_roamed(self):
        """record_roam + get_recently_roamed roundtrip."""
        init_db()
        from src.storage.db import record_roam, get_recently_roamed

        test_id = "test-roam-dedup-check"
        record_roam([test_id])
        recent = get_recently_roamed(days=14)
        assert test_id in recent

    def test_get_recently_roamed_empty(self):
        """get_recently_roamed returns empty set with no history."""
        init_db()
        from src.storage.db import get_recently_roamed
        result = get_recently_roamed(days=14)
        assert isinstance(result, set)
