"""Suggestion service — ties anchor resolution + storage + markdown apply.

create_pending: resolve quote against canonical content_md, store pending row.
resolve(accept): drift-check, apply markdown replacement, bump revision.
resolve(reject): leave document untouched.
"""

import pytest

from src.storage import db
from src.workspace import suggestions as svc
from src.workspace.anchor import AnchorNotFound


@pytest.fixture(autouse=True)
def _init_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()


def _doc(doc_id="d1", html="<p>The quick brown fox jumps.</p>"):
    db.insert_workspace_document(doc_id, title="T", content=html)
    return doc_id


class TestCreatePending:
    def test_create_resolves_anchor_and_stores(self):
        _doc()
        s = svc.create_pending(
            document_id="d1", quote="quick brown fox",
            new_content="lazy red cat", created_by="agent:copilot",
        )
        assert s["status"] == "pending"
        pend = db.get_pending_suggestion("d1")
        assert pend["id"] == s["id"]
        assert pend["new_content"] == "lazy red cat"

    def test_quote_not_found_propagates(self):
        _doc()
        with pytest.raises(AnchorNotFound):
            svc.create_pending(
                document_id="d1", quote="not in document",
                new_content="x", created_by="agent:copilot",
            )

    def test_second_pending_blocked(self):
        _doc()
        svc.create_pending(document_id="d1", quote="quick",
                            new_content="slow", created_by="agent:copilot")
        with pytest.raises(ValueError, match="PENDING_SUGGESTION_EXISTS"):
            svc.create_pending(document_id="d1", quote="fox",
                               new_content="cat", created_by="agent:copilot")


class TestResolveAccept:
    def test_accept_applies_and_bumps_revision(self):
        _doc()
        before = db.get_workspace_document("d1")
        s = svc.create_pending(document_id="d1", quote="quick brown fox",
                               new_content="lazy red cat", created_by="agent:copilot")
        svc.resolve(s["id"], action="accept", resolved_by="human:yrzhe")
        after = db.get_workspace_document("d1")
        assert "lazy red cat" in after["content_md"]
        assert "quick brown fox" not in after["content_md"]
        assert after["revision"] == before["revision"] + 1
        assert db.get_pending_suggestion("d1") is None
        assert db.get_workspace_suggestion(s["id"])["status"] == "accepted"

    def test_accept_refuses_on_drift(self):
        _doc()
        s = svc.create_pending(document_id="d1", quote="quick brown fox",
                               new_content="lazy red cat", created_by="agent:copilot")
        # human edits the anchored text out from under the pending suggestion
        db.update_workspace_document("d1", content="<p>The slow green turtle waits.</p>")
        with pytest.raises(svc.SuggestionDrifted):
            svc.resolve(s["id"], action="accept", resolved_by="human:yrzhe")
        # document must be untouched by the failed accept
        assert "slow green turtle" in db.get_workspace_document("d1")["content_md"]


class TestResolveReject:
    def test_reject_leaves_document_untouched(self):
        _doc()
        before = db.get_workspace_document("d1")
        s = svc.create_pending(document_id="d1", quote="quick brown fox",
                               new_content="lazy red cat", created_by="agent:copilot")
        svc.resolve(s["id"], action="reject", resolved_by="human:yrzhe",
                    rejection_reason="not now")
        after = db.get_workspace_document("d1")
        assert after["content_md"] == before["content_md"]
        assert after["revision"] == before["revision"]
        assert db.get_workspace_suggestion(s["id"])["status"] == "rejected"
