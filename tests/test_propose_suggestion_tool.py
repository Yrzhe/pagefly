"""Agent write tool: propose_workspace_suggestion.

The agent can PROPOSE a character-level edit (one pending per doc); it still
cannot mutate document content directly — acceptance is the human's call.
"""

import asyncio

import pytest

from src.agents import base
from src.storage import db


@pytest.fixture(autouse=True)
def _init_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()


def _call(args):
    return asyncio.run(base.propose_workspace_suggestion.handler(args))


def _text(res):
    return res["content"][0]["text"]


def _doc(doc_id="d1", html="<p>The quick brown fox jumps.</p>"):
    db.insert_workspace_document(doc_id, title="T", content=html)
    return doc_id


class TestProposeTool:
    def test_proposes_pending_suggestion(self):
        _doc()
        res = _call({
            "doc_id": "d1", "quote": "quick brown fox",
            "replacement": "lazy red cat", "reason": "tighter imagery",
        })
        txt = _text(res)
        pend = db.get_pending_suggestion("d1")
        assert pend is not None
        assert pend["new_content"] == "lazy red cat"
        assert pend["id"] in txt          # surfaces the id
        assert "tighter imagery" in txt   # surfaces the reason to the human

    def test_anchor_not_found_is_recoverable(self):
        _doc()
        res = _call({
            "doc_id": "d1", "quote": "text that is absent",
            "replacement": "x", "reason": "r",
        })
        txt = _text(res).lower()
        assert "not" in txt and "found" in txt        # tells the agent to retry
        assert db.get_pending_suggestion("d1") is None  # nothing created

    def test_second_pending_reports_conflict(self):
        _doc()
        _call({"doc_id": "d1", "quote": "quick", "replacement": "slow", "reason": "r"})
        res = _call({"doc_id": "d1", "quote": "fox", "replacement": "cat", "reason": "r"})
        assert "pending" in _text(res).lower()

    def test_unknown_document(self):
        res = _call({
            "doc_id": "nope", "quote": "x", "replacement": "y", "reason": "r",
        })
        assert "not found" in _text(res).lower()

    def test_tool_cannot_mutate_content_directly(self):
        _doc()
        before = db.get_workspace_document("d1")["content"]
        _call({"doc_id": "d1", "quote": "quick brown fox",
                     "replacement": "lazy red cat", "reason": "r"})
        # proposing must NOT change the document — only a human accept does
        assert db.get_workspace_document("d1")["content"] == before
