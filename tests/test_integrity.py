"""Tests for src/shared/integrity — deterministic auto-fix functions."""

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from src.shared.integrity import (
    IntegrityReport,
    fix_ghost_references,
    fix_orphan_connection_backlinks,
    fix_db_orphans,
    check_document,
    full_integrity_check,
)


# ── Helpers ──


def _write_meta(path: Path, meta: dict) -> Path:
    """Write metadata.json and document.md to a directory."""
    path.mkdir(parents=True, exist_ok=True)
    (path / "metadata.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (path / "document.md").write_text("# Test", encoding="utf-8")
    return path


def _read_meta(path: Path) -> dict:
    """Read metadata.json from a directory."""
    return json.loads((path / "metadata.json").read_text(encoding="utf-8"))


# ── fix_ghost_references ──


class TestFixGhostReferences:
    def test_removes_ghost_source_doc_ids(self, tmp_path):
        """Ghost source_doc_ids are removed, valid ones kept."""
        wiki_dir = tmp_path / "wiki"
        valid_id = "aaaa-valid-id"
        ghost_id = "bbbb-ghost-id"

        _write_meta(wiki_dir / "concept" / "test_article", {
            "id": "article-1",
            "title": "Test Article",
            "article_type": "concept",
            "source_document_ids": [valid_id, ghost_id],
            "references": [],
        })

        all_ids = {valid_id, "article-1"}
        report = IntegrityReport()

        with patch("src.shared.integrity.WIKI_DIR", wiki_dir):
            with patch("src.shared.integrity.db") as mock_db:
                fix_ghost_references(all_ids, report)

        meta = _read_meta(wiki_dir / "concept" / "test_article")
        assert meta["source_document_ids"] == [valid_id]
        assert len(report.auto_fixed) == 1
        assert "ghost source_doc_id" in report.auto_fixed[0]
        mock_db.update_wiki_article.assert_called_once()

    def test_removes_ghost_references(self, tmp_path):
        """References with non-existent target_id are removed."""
        wiki_dir = tmp_path / "wiki"
        valid_id = "aaaa-valid-id"
        ghost_id = "cccc-ghost-id"

        _write_meta(wiki_dir / "concept" / "test_art", {
            "id": "art-1",
            "title": "Test",
            "article_type": "concept",
            "source_document_ids": [valid_id],
            "references": [
                {"target_id": valid_id, "relation": "source", "confidence": 1.0},
                {"target_id": ghost_id, "relation": "related_concept", "confidence": 0.5},
            ],
        })

        all_ids = {valid_id, "art-1"}
        report = IntegrityReport()

        with patch("src.shared.integrity.WIKI_DIR", wiki_dir):
            with patch("src.shared.integrity.db"):
                fix_ghost_references(all_ids, report)

        meta = _read_meta(wiki_dir / "concept" / "test_art")
        assert len(meta["references"]) == 1
        assert meta["references"][0]["target_id"] == valid_id
        assert len(report.auto_fixed) == 1
        assert "ghost reference" in report.auto_fixed[0]

    def test_preserves_valid_references(self, tmp_path):
        """When all references are valid, nothing changes."""
        wiki_dir = tmp_path / "wiki"
        id_a = "aaaa-id"
        id_b = "bbbb-id"

        _write_meta(wiki_dir / "concept" / "ok_art", {
            "id": "art-ok",
            "title": "OK Article",
            "article_type": "concept",
            "source_document_ids": [id_a],
            "references": [
                {"target_id": id_a, "relation": "source", "confidence": 1.0},
                {"target_id": id_b, "relation": "related_concept", "confidence": 0.8},
            ],
        })

        all_ids = {id_a, id_b, "art-ok"}
        report = IntegrityReport()

        with patch("src.shared.integrity.WIKI_DIR", wiki_dir):
            with patch("src.shared.integrity.db"):
                fix_ghost_references(all_ids, report)

        assert len(report.auto_fixed) == 0
        meta = _read_meta(wiki_dir / "concept" / "ok_art")
        assert len(meta["references"]) == 2
        assert len(meta["source_document_ids"]) == 1

    def test_removes_malformed_references(self, tmp_path):
        """Non-dict references are dropped."""
        wiki_dir = tmp_path / "wiki"

        _write_meta(wiki_dir / "concept" / "bad_refs", {
            "id": "art-bad",
            "title": "Bad Refs",
            "article_type": "concept",
            "source_document_ids": [],
            "references": [
                "not-a-dict",
                {"target_id": "art-bad", "relation": "source", "confidence": 1.0},
            ],
        })

        all_ids = {"art-bad"}
        report = IntegrityReport()

        with patch("src.shared.integrity.WIKI_DIR", wiki_dir):
            with patch("src.shared.integrity.db"):
                fix_ghost_references(all_ids, report)

        meta = _read_meta(wiki_dir / "concept" / "bad_refs")
        assert len(meta["references"]) == 1
        assert meta["references"][0]["target_id"] == "art-bad"


# ── fix_orphan_connection_backlinks ──


class TestFixOrphanConnectionBacklinks:
    def test_adds_missing_backlink(self, tmp_path):
        """Connection's referenced concept gets a backlink added."""
        wiki_dir = tmp_path / "wiki"
        knowledge_dir = tmp_path / "knowledge"

        concept_id = "concept-aaa"
        connection_id = "conn-bbb"

        # Create concept without backlink to connection
        _write_meta(wiki_dir / "concept" / "test_concept", {
            "id": concept_id,
            "title": "Test Concept",
            "article_type": "concept",
            "source_document_ids": [],
            "references": [],
        })

        # Create connection that references the concept
        _write_meta(wiki_dir / "connection" / "test_conn", {
            "id": connection_id,
            "title": "A ↔ B Connection",
            "article_type": "connection",
            "source_document_ids": [],
            "references": [
                {"target_id": concept_id, "relation": "related_concept", "confidence": 0.9},
            ],
        })

        all_ids = {concept_id, connection_id}
        report = IntegrityReport()

        with patch("src.shared.integrity.WIKI_DIR", wiki_dir):
            with patch("src.shared.integrity.KNOWLEDGE_DIR", knowledge_dir):
                fix_orphan_connection_backlinks(all_ids, report)

        # Concept should now have a backlink
        concept_meta = _read_meta(wiki_dir / "concept" / "test_concept")
        assert len(concept_meta["references"]) == 1
        assert concept_meta["references"][0]["target_id"] == connection_id
        assert concept_meta["references"][0]["relation"] == "related_concept"
        assert len(report.auto_fixed) == 1
        assert "backlink" in report.auto_fixed[0]

    def test_skips_existing_backlink(self, tmp_path):
        """No duplicate backlink if concept already references the connection."""
        wiki_dir = tmp_path / "wiki"
        knowledge_dir = tmp_path / "knowledge"

        concept_id = "concept-ccc"
        connection_id = "conn-ddd"

        _write_meta(wiki_dir / "concept" / "linked_concept", {
            "id": concept_id,
            "title": "Linked Concept",
            "article_type": "concept",
            "source_document_ids": [],
            "references": [
                {"target_id": connection_id, "relation": "related_concept", "confidence": 0.8},
            ],
        })

        _write_meta(wiki_dir / "connection" / "existing_conn", {
            "id": connection_id,
            "title": "Existing Connection",
            "article_type": "connection",
            "source_document_ids": [],
            "references": [
                {"target_id": concept_id, "relation": "related_concept", "confidence": 0.9},
            ],
        })

        all_ids = {concept_id, connection_id}
        report = IntegrityReport()

        with patch("src.shared.integrity.WIKI_DIR", wiki_dir):
            with patch("src.shared.integrity.KNOWLEDGE_DIR", knowledge_dir):
                fix_orphan_connection_backlinks(all_ids, report)

        concept_meta = _read_meta(wiki_dir / "concept" / "linked_concept")
        assert len(concept_meta["references"]) == 1  # No duplicate
        assert len(report.auto_fixed) == 0

    def test_backlinks_knowledge_docs(self, tmp_path):
        """Connection referencing a knowledge doc also gets backlinked."""
        wiki_dir = tmp_path / "wiki"
        knowledge_dir = tmp_path / "knowledge"

        doc_id = "doc-eee"
        connection_id = "conn-fff"

        _write_meta(knowledge_dir / "research" / "test_doc", {
            "id": doc_id,
            "title": "Research Doc",
            "source_type": "text",
            "status": "classified",
            "ingested_at": "2026-01-01T00:00:00",
            "references": [],
        })

        _write_meta(wiki_dir / "connection" / "doc_conn", {
            "id": connection_id,
            "title": "Doc ↔ Concept",
            "article_type": "connection",
            "source_document_ids": [doc_id],
            "references": [
                {"target_id": doc_id, "relation": "source", "confidence": 1.0},
            ],
        })

        all_ids = {doc_id, connection_id}
        report = IntegrityReport()

        with patch("src.shared.integrity.WIKI_DIR", wiki_dir):
            with patch("src.shared.integrity.KNOWLEDGE_DIR", knowledge_dir):
                fix_orphan_connection_backlinks(all_ids, report)

        doc_meta = _read_meta(knowledge_dir / "research" / "test_doc")
        assert len(doc_meta["references"]) == 1
        assert doc_meta["references"][0]["target_id"] == connection_id


# ── fix_db_orphans ──


class TestFixDbOrphans:
    def test_registers_knowledge_doc_in_db(self, tmp_path):
        """Doc on disk but not in DB gets inserted."""
        knowledge_dir = tmp_path / "knowledge"
        wiki_dir = tmp_path / "wiki"
        wiki_dir.mkdir()

        doc_id = "doc-orphan-111"
        _write_meta(knowledge_dir / "tech" / "orphan_doc", {
            "id": doc_id,
            "title": "Orphan Doc",
            "source_type": "text",
            "status": "classified",
            "ingested_at": "2026-01-01T00:00:00",
            "category": "tech",
            "subcategory": "python",
            "tags": ["test"],
        })

        report = IntegrityReport()

        with patch("src.shared.integrity.KNOWLEDGE_DIR", knowledge_dir):
            with patch("src.shared.integrity.WIKI_DIR", wiki_dir):
                with patch("src.shared.integrity.db") as mock_db:
                    mock_db.get_document.return_value = None
                    fix_db_orphans(set(), set(), report)

        mock_db.insert_document.assert_called_once_with(
            doc_id=doc_id,
            source_type="text",
            original_filename="",
            current_path=str(knowledge_dir / "tech" / "orphan_doc"),
            ingested_at="2026-01-01T00:00:00",
            title="Orphan Doc",
        )
        mock_db.update_document.assert_called_once()
        assert len(report.auto_fixed) == 1
        assert "registered in DB" in report.auto_fixed[0]

    def test_skips_existing_db_record(self, tmp_path):
        """Doc already in DB is not re-inserted."""
        knowledge_dir = tmp_path / "knowledge"
        wiki_dir = tmp_path / "wiki"
        wiki_dir.mkdir()

        doc_id = "doc-exists-222"
        _write_meta(knowledge_dir / "tech" / "existing_doc", {
            "id": doc_id,
            "title": "Existing Doc",
            "source_type": "text",
            "status": "classified",
            "ingested_at": "2026-01-01T00:00:00",
        })

        report = IntegrityReport()

        with patch("src.shared.integrity.KNOWLEDGE_DIR", knowledge_dir):
            with patch("src.shared.integrity.WIKI_DIR", wiki_dir):
                with patch("src.shared.integrity.db") as mock_db:
                    mock_db.get_document.return_value = {"id": doc_id}
                    fix_db_orphans(set(), set(), report)

        mock_db.insert_document.assert_not_called()
        assert len(report.auto_fixed) == 0

    def test_registers_wiki_article_in_db(self, tmp_path):
        """Wiki article on disk but not in DB gets inserted."""
        knowledge_dir = tmp_path / "knowledge"
        knowledge_dir.mkdir()
        wiki_dir = tmp_path / "wiki"

        article_id = "wiki-orphan-333"
        _write_meta(wiki_dir / "concept" / "orphan_article", {
            "id": article_id,
            "title": "Orphan Wiki",
            "article_type": "concept",
            "summary": "A test concept",
            "source_document_ids": [],
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
        })

        report = IntegrityReport()

        # Mock the DB connection for wiki check
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = None

        with patch("src.shared.integrity.KNOWLEDGE_DIR", knowledge_dir):
            with patch("src.shared.integrity.WIKI_DIR", wiki_dir):
                with patch("src.shared.integrity.db") as mock_db:
                    mock_db.get_connection.return_value = mock_conn
                    mock_db.transaction.return_value.__enter__ = MagicMock(return_value=mock_conn)
                    mock_db.transaction.return_value.__exit__ = MagicMock(return_value=False)
                    fix_db_orphans(set(), set(), report)

        assert len(report.auto_fixed) == 1
        assert "wiki article registered in DB" in report.auto_fixed[0]


# ── check_document ──


class TestCheckDocument:
    def test_missing_document_md(self, tmp_path):
        """Reports error if document.md is missing."""
        doc_dir = tmp_path / "test_doc"
        doc_dir.mkdir()
        (doc_dir / "metadata.json").write_text(
            json.dumps({"id": "test-id", "title": "Test", "status": "raw", "source_type": "text", "ingested_at": "2026-01-01"}),
            encoding="utf-8",
        )

        with patch("src.shared.integrity.db") as mock_db:
            mock_db.get_document.return_value = {"id": "test-id", "current_path": str(doc_dir)}
            report = check_document(doc_dir)

        assert any("missing document.md" in e for e in report.errors)

    def test_missing_metadata_json(self, tmp_path):
        """Reports error if metadata.json is missing."""
        doc_dir = tmp_path / "test_doc"
        doc_dir.mkdir()
        (doc_dir / "document.md").write_text("# Test", encoding="utf-8")

        report = check_document(doc_dir)
        assert any("missing metadata.json" in e for e in report.errors)

    def test_valid_document(self, tmp_path):
        """No errors for a valid document."""
        doc_dir = tmp_path / "test_doc"
        _write_meta(doc_dir, {
            "id": "valid-id",
            "title": "Valid",
            "status": "classified",
            "source_type": "text",
            "ingested_at": "2026-01-01T00:00:00",
        })

        with patch("src.shared.integrity.db") as mock_db:
            mock_db.get_document.return_value = {"id": "valid-id", "current_path": str(doc_dir)}
            report = check_document(doc_dir)

        assert report.ok


# ── IntegrityReport ──


class TestIntegrityReport:
    def test_empty_report(self):
        report = IntegrityReport()
        assert report.ok
        assert report.summary() == "All checks passed"
        assert "All checks passed" in report.to_markdown()

    def test_report_with_issues(self):
        report = IntegrityReport()
        report.errors.append("test error")
        report.warnings.append("test warning")
        report.auto_fixed.append("test fix")

        assert not report.ok
        assert "Errors: 1" in report.summary()
        assert "Warnings: 1" in report.summary()
        assert "Auto-fixed: 1" in report.summary()

        md = report.to_markdown()
        assert "## Auto-fixed (1)" in md
        assert "## Warnings (1)" in md
        assert "## Errors (1)" in md
