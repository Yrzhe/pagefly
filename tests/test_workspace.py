"""Tests for workspace_documents DB operations and API endpoints."""

import pytest
from src.storage import db


@pytest.fixture(autouse=True)
def _init_db(tmp_path, monkeypatch):
    """Use a temporary database for each test."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()


class TestWorkspaceDocumentsDB:
    def test_insert_and_get(self):
        db.insert_workspace_document("ws-1", title="Test Doc", content="<p>hello</p>")
        doc = db.get_workspace_document("ws-1")
        assert doc is not None
        assert doc["title"] == "Test Doc"
        assert doc["content"] == "<p>hello</p>"
        assert doc["revision"] == 1
        assert doc["status"] == "draft"
        assert doc["created_by"] == "human"

    def test_list_documents(self):
        db.insert_workspace_document("ws-1", title="A")
        db.insert_workspace_document("ws-2", title="B", status="review")
        docs = db.list_workspace_documents()
        assert len(docs) == 2
        # Should not include full content in list
        assert "content" not in docs[0]

    def test_list_filter_by_status(self):
        db.insert_workspace_document("ws-1", title="A", status="draft")
        db.insert_workspace_document("ws-2", title="B", status="review")
        drafts = db.list_workspace_documents(status="draft")
        assert len(drafts) == 1
        assert drafts[0]["title"] == "A"

    def test_update_bumps_revision(self):
        db.insert_workspace_document("ws-1", title="A", content="<p>v1</p>")
        new_rev = db.update_workspace_document("ws-1", content="<p>v2</p>")
        assert new_rev == 2
        doc = db.get_workspace_document("ws-1")
        assert doc["content"] == "<p>v2</p>"
        assert doc["revision"] == 2

    def test_update_title_no_revision_bump(self):
        db.insert_workspace_document("ws-1", title="A")
        new_rev = db.update_workspace_document("ws-1", title="B")
        assert new_rev == 1  # title-only change doesn't bump revision

    def test_optimistic_lock_conflict(self):
        db.insert_workspace_document("ws-1", title="A", content="<p>v1</p>")
        # Correct revision
        db.update_workspace_document("ws-1", expected_revision=1, content="<p>v2</p>")
        # Wrong revision should raise
        with pytest.raises(ValueError, match="Conflict"):
            db.update_workspace_document("ws-1", expected_revision=1, content="<p>v3</p>")

    def test_delete(self):
        db.insert_workspace_document("ws-1", title="A")
        assert db.delete_workspace_document("ws-1") is True
        assert db.get_workspace_document("ws-1") is None

    def test_delete_nonexistent(self):
        assert db.delete_workspace_document("nope") is False

    def test_get_nonexistent(self):
        assert db.get_workspace_document("nope") is None
