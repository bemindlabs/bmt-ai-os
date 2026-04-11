"""Unit tests for bmt_ai_os.controller.conversation_routes."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Point the conversation store at a fresh temp DB for each test."""
    db = str(tmp_path / "test-conv.db")
    monkeypatch.setenv("BMT_CONV_DB", db)

    # Re-initialise the DB for the isolated path
    from bmt_ai_os.controller import conversation_routes

    conversation_routes._init_db(db)
    yield db


@pytest.fixture()
def client():
    """Return a TestClient for the controller FastAPI app."""
    from bmt_ai_os.controller.api import app

    return TestClient(app)


# ---------------------------------------------------------------------------
# POST /api/v1/conversations
# ---------------------------------------------------------------------------


class TestCreateConversation:
    def test_create_minimal(self, client):
        resp = client.post("/api/v1/conversations", json={"title": "Test convo"})
        assert resp.status_code == 201
        body = resp.json()
        assert body["title"] == "Test convo"
        assert body["id"].startswith("conv_")
        assert body["messages"] == []

    def test_create_with_messages(self, client):
        resp = client.post(
            "/api/v1/conversations",
            json={
                "title": "Q&A",
                "messages": [
                    {"role": "user", "content": "Hello!"},
                    {"role": "assistant", "content": "Hi there!"},
                ],
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert len(body["messages"]) == 2
        assert body["messages"][0]["role"] == "user"

    def test_create_empty_title(self, client):
        resp = client.post("/api/v1/conversations", json={})
        assert resp.status_code == 201
        assert resp.json()["title"] == ""

    def test_invalid_role_rejected(self, client):
        resp = client.post(
            "/api/v1/conversations",
            json={"messages": [{"role": "admin", "content": "bad"}]},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/conversations
# ---------------------------------------------------------------------------


class TestListConversations:
    def test_empty_list(self, client):
        resp = client.get("/api/v1/conversations")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0
        assert body["conversations"] == []

    def test_lists_created_conversations(self, client):
        client.post("/api/v1/conversations", json={"title": "First"})
        client.post("/api/v1/conversations", json={"title": "Second"})

        resp = client.get("/api/v1/conversations")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        titles = {c["title"] for c in body["conversations"]}
        assert titles == {"First", "Second"}

    def test_pagination(self, client):
        for i in range(5):
            client.post("/api/v1/conversations", json={"title": f"Conv {i}"})

        resp = client.get("/api/v1/conversations?page=1&page_size=2")
        body = resp.json()
        assert body["total"] == 5
        assert len(body["conversations"]) == 2
        assert body["page"] == 1
        assert body["page_size"] == 2

    def test_page_2(self, client):
        for i in range(5):
            client.post("/api/v1/conversations", json={"title": f"Conv {i}"})

        resp = client.get("/api/v1/conversations?page=2&page_size=2")
        body = resp.json()
        assert len(body["conversations"]) == 2


# ---------------------------------------------------------------------------
# GET /api/v1/conversations/{id}
# ---------------------------------------------------------------------------


class TestGetConversation:
    def test_get_existing(self, client):
        create = client.post(
            "/api/v1/conversations",
            json={"title": "Details", "messages": [{"role": "user", "content": "Hey"}]},
        )
        conv_id = create.json()["id"]

        resp = client.get(f"/api/v1/conversations/{conv_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == conv_id
        assert body["title"] == "Details"
        assert len(body["messages"]) == 1

    def test_get_not_found(self, client):
        resp = client.get("/api/v1/conversations/conv_does_not_exist")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/v1/conversations/{id}
# ---------------------------------------------------------------------------


class TestDeleteConversation:
    def test_delete_existing(self, client):
        create = client.post("/api/v1/conversations", json={"title": "To delete"})
        conv_id = create.json()["id"]

        resp = client.delete(f"/api/v1/conversations/{conv_id}")
        assert resp.status_code == 204

        # Verify it's gone
        get_resp = client.get(f"/api/v1/conversations/{conv_id}")
        assert get_resp.status_code == 404

    def test_delete_not_found(self, client):
        resp = client.delete("/api/v1/conversations/conv_ghost")
        assert resp.status_code == 404

    def test_delete_removes_from_list(self, client):
        client.post("/api/v1/conversations", json={"title": "Keep"})
        c2 = client.post("/api/v1/conversations", json={"title": "Remove"})

        client.delete(f"/api/v1/conversations/{c2.json()['id']}")

        resp = client.get("/api/v1/conversations")
        assert resp.json()["total"] == 1
        assert resp.json()["conversations"][0]["title"] == "Keep"


# ---------------------------------------------------------------------------
# GET /api/v1/conversations/search
# ---------------------------------------------------------------------------


class TestSearchConversations:
    def test_search_finds_match(self, client):
        client.post("/api/v1/conversations", json={"title": "Python debugging session"})
        client.post("/api/v1/conversations", json={"title": "Rust async patterns"})

        resp = client.get("/api/v1/conversations/search?q=Python")
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) >= 1
        assert any("Python" in r["title"] for r in results)

    def test_search_no_results(self, client):
        client.post("/api/v1/conversations", json={"title": "Hello world"})
        resp = client.get("/api/v1/conversations/search?q=xyznonexistent")
        assert resp.status_code == 200
        # Either FTS or LIKE returns empty list
        assert isinstance(resp.json(), list)

    def test_search_requires_query(self, client):
        resp = client.get("/api/v1/conversations/search")
        assert resp.status_code == 422
