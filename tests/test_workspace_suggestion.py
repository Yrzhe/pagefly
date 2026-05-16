"""workspace_suggestions storage — single-pending rule (spec §2.5 / §4.5),
adapted to SQLite partial unique index.
"""

import pytest

from src.storage import db


@pytest.fixture(autouse=True)
def _init_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()


def _mk_doc(doc_id="d1"):
    db.insert_workspace_document(doc_id, title="T", content="<p>hello world</p>")
    return doc_id


def _suggestion_kwargs(**over):
    base = dict(
        document_id="d1",
        kind="replace",
        quote="hello",
        prefix=None,
        suffix=None,
        range_start=0,
        range_end=5,
        new_content="hi",
        content_hash="abc",
        created_by="agent:copilot",
    )
    base.update(over)
    return base


class TestCreateAndFetch:
    def test_create_then_get_pending(self):
        _mk_doc()
        sid = db.create_workspace_suggestion(**_suggestion_kwargs())
        pend = db.get_pending_suggestion("d1")
        assert pend is not None
        assert pend["id"] == sid
        assert pend["status"] == "pending"
        assert pend["new_content"] == "hi"

    def test_no_pending_returns_none(self):
        _mk_doc()
        assert db.get_pending_suggestion("d1") is None


class TestSinglePendingRule:
    def test_second_pending_rejected(self):
        _mk_doc()
        db.create_workspace_suggestion(**_suggestion_kwargs())
        with pytest.raises(ValueError, match="PENDING_SUGGESTION_EXISTS"):
            db.create_workspace_suggestion(**_suggestion_kwargs(quote="world", range_start=6, range_end=11))

    def test_new_pending_ok_after_resolve(self):
        _mk_doc()
        sid = db.create_workspace_suggestion(**_suggestion_kwargs())
        db.resolve_workspace_suggestion(sid, action="reject", resolved_by="human:yrzhe")
        # previous no longer pending → a new one is allowed
        sid2 = db.create_workspace_suggestion(**_suggestion_kwargs(quote="world", range_start=6, range_end=11))
        assert db.get_pending_suggestion("d1")["id"] == sid2


class TestResolve:
    def test_accept_sets_status_and_resolver(self):
        _mk_doc()
        sid = db.create_workspace_suggestion(**_suggestion_kwargs())
        db.resolve_workspace_suggestion(sid, action="accept", resolved_by="human:yrzhe")
        row = db.get_workspace_suggestion(sid)
        assert row["status"] == "accepted"
        assert row["resolved_by"] == "human:yrzhe"
        assert row["resolved_at"] is not None

    def test_reject_records_reason(self):
        _mk_doc()
        sid = db.create_workspace_suggestion(**_suggestion_kwargs())
        db.resolve_workspace_suggestion(
            sid, action="reject", resolved_by="human:yrzhe", rejection_reason="not now"
        )
        row = db.get_workspace_suggestion(sid)
        assert row["status"] == "rejected"
        assert row["rejection_reason"] == "not now"

    def test_invalid_action_raises(self):
        _mk_doc()
        sid = db.create_workspace_suggestion(**_suggestion_kwargs())
        with pytest.raises(ValueError):
            db.resolve_workspace_suggestion(sid, action="bogus", resolved_by="human:yrzhe")
