"""API endpoints for the workspace suggestion flow (Phase 2).

POST   /api/workspace/documents/{id}/suggestions            create (Idempotency-Key)
GET    /api/workspace/documents/{id}/suggestions            the pending one (or null)
POST   /api/workspace/documents/{id}/suggestions/{sid}/resolve   accept | reject
"""

import pytest
from fastapi.testclient import TestClient

from src.channels.api import app, verify_token
from src.storage import db


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    app.dependency_overrides[verify_token] = lambda: None
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    return TestClient(app)


def _doc(client, doc_id="d1", html="<p>The quick brown fox jumps.</p>"):
    db.insert_workspace_document(doc_id, title="T", content=html)
    return doc_id


class TestCreate:
    def test_create_returns_pending(self, client):
        _doc(client)
        r = client.post(
            "/api/workspace/documents/d1/suggestions",
            json={"quote": "quick brown fox", "new_content": "lazy red cat",
                  "created_by": "agent:copilot"},
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["status"] == "pending"
        assert body["new_content"] == "lazy red cat"

    def test_quote_not_found_is_422(self, client):
        _doc(client)
        r = client.post(
            "/api/workspace/documents/d1/suggestions",
            json={"quote": "nope", "new_content": "x", "created_by": "agent:copilot"},
        )
        assert r.status_code == 422
        assert r.json()["detail"]["reason"] == "quote_not_found"

    def test_second_pending_is_409(self, client):
        _doc(client)
        client.post("/api/workspace/documents/d1/suggestions",
                    json={"quote": "quick", "new_content": "slow", "created_by": "a"})
        r = client.post("/api/workspace/documents/d1/suggestions",
                        json={"quote": "fox", "new_content": "cat", "created_by": "a"})
        assert r.status_code == 409
        assert "PENDING_SUGGESTION_EXISTS" in r.json()["detail"]

    def test_idempotency_key_replays(self, client):
        _doc(client)
        headers = {"Idempotency-Key": "k-123"}
        payload = {"quote": "quick", "new_content": "slow", "created_by": "a"}
        r1 = client.post("/api/workspace/documents/d1/suggestions",
                         json=payload, headers=headers)
        r2 = client.post("/api/workspace/documents/d1/suggestions",
                         json=payload, headers=headers)
        assert r1.status_code == 201
        assert r2.status_code == 201
        assert r1.json()["id"] == r2.json()["id"]  # replay, not a 409


class TestGet:
    def test_get_pending(self, client):
        _doc(client)
        client.post("/api/workspace/documents/d1/suggestions",
                    json={"quote": "quick", "new_content": "slow", "created_by": "a"})
        r = client.get("/api/workspace/documents/d1/suggestions")
        assert r.status_code == 200
        assert r.json()["pending"]["new_content"] == "slow"

    def test_get_none(self, client):
        _doc(client)
        r = client.get("/api/workspace/documents/d1/suggestions")
        assert r.status_code == 200
        assert r.json()["pending"] is None


class TestResolve:
    def _create(self, client):
        _doc(client)
        return client.post(
            "/api/workspace/documents/d1/suggestions",
            json={"quote": "quick brown fox", "new_content": "lazy red cat",
                  "created_by": "agent:copilot"},
        ).json()["id"]

    def test_accept_applies(self, client):
        sid = self._create(client)
        r = client.post(
            f"/api/workspace/documents/d1/suggestions/{sid}/resolve",
            json={"action": "accept", "resolved_by": "human:yrzhe"},
        )
        assert r.status_code == 200
        doc = db.get_workspace_document("d1")
        assert "lazy red cat" in doc["content_md"]
        assert db.get_pending_suggestion("d1") is None

    def test_reject_untouched(self, client):
        sid = self._create(client)
        before = db.get_workspace_document("d1")["content_md"]
        r = client.post(
            f"/api/workspace/documents/d1/suggestions/{sid}/resolve",
            json={"action": "reject", "resolved_by": "human:yrzhe"},
        )
        assert r.status_code == 200
        assert db.get_workspace_document("d1")["content_md"] == before

    def test_accept_on_drift_is_409(self, client):
        sid = self._create(client)
        db.update_workspace_document("d1", content="<p>totally different now.</p>")
        r = client.post(
            f"/api/workspace/documents/d1/suggestions/{sid}/resolve",
            json={"action": "accept", "resolved_by": "human:yrzhe"},
        )
        assert r.status_code == 409
        assert "drift" in r.json()["detail"].lower()
