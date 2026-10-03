"""Tests for tool_server.py — the OpenAPI tool surface a local model calls.

Every test drives the app through FastAPI's TestClient with retrieval and store
lookups monkeypatched, so no embedding model, reranker, or ChromaDB is touched.
Skipped entirely when the optional server dependencies are not installed.
"""

import logging
import sys

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

import tool_server  # noqa: E402

TOKEN = "test-token-3f9a1c"
AUTH = {"Authorization": f"Bearer {TOKEN}"}

DOCS = {"study": ["docA", "docB"], "work": ["docC"]}


@pytest.fixture
def fake_store(monkeypatch):
    """Stub the store lookups. Returns a dict later tests use to steer the search."""
    state: dict = {}

    def fake_list_documents(project=None):
        if project is None:
            return sorted(d for docs in DOCS.values() for d in docs)
        return sorted(DOCS.get(project, []))

    monkeypatch.setattr(tool_server, "list_projects", lambda: sorted(DOCS))
    monkeypatch.setattr(tool_server, "list_documents", fake_list_documents)
    return state


@pytest.fixture
def client(fake_store):
    return TestClient(tool_server.create_app(token=TOKEN, warm=False))


# ── Skeleton: health, auth, bind rule ───────────────────────────────


def test_health_needs_no_token(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_bearer_token_required_when_configured(client):
    assert client.get("/list_documents").status_code == 401
    wrong = client.get("/list_documents", headers={"Authorization": "Bearer wrong"})
    assert wrong.status_code == 401
    assert wrong.headers["www-authenticate"] == "Bearer"
    assert client.get("/list_documents", headers=AUTH).status_code == 200


def test_no_token_configured_is_open(fake_store):
    """Loopback mode: with no token set, the tool endpoints need no header."""
    open_client = TestClient(tool_server.create_app(token=None, warm=False))
    assert open_client.get("/list_documents").status_code == 200


def test_non_loopback_bind_requires_token():
    """Fail closed: a network-reachable bind without a token would publish every
    ingested document unauthenticated."""
    tool_server.check_bind("127.0.0.1", None)
    tool_server.check_bind("localhost", None)
    tool_server.check_bind("0.0.0.0", "tok")
    with pytest.raises(ValueError, match=tool_server.SERVE_TOKEN_ENV):
        tool_server.check_bind("0.0.0.0", None)
    with pytest.raises(ValueError):
        tool_server.check_bind("192.168.1.20", "")


def test_token_never_appears_in_logs(client, caplog):
    """A rejected request is logged (so a misconfigured client is debuggable),
    but neither the configured token nor the supplied one is."""
    caplog.set_level(logging.DEBUG)
    client.get("/list_documents")
    client.get("/list_documents", headers={"Authorization": "Bearer wrong-secret"})
    client.get("/list_documents", headers=AUTH)
    assert "rejected" in caplog.text
    assert TOKEN not in caplog.text
    assert "wrong-secret" not in caplog.text


# ── list_documents ──────────────────────────────────────────────────


def test_list_documents_groups_by_project(client):
    r = client.get("/list_documents", headers=AUTH)
    assert r.json() == {"projects": {"study": ["docA", "docB"], "work": ["docC"]}}
    scoped = client.get("/list_documents", params={"project": "work"}, headers=AUTH)
    assert scoped.json() == {"projects": {"work": ["docC"]}}


def test_list_documents_unknown_project_is_404(client):
    r = client.get("/list_documents", params={"project": "nope"}, headers=AUTH)
    assert r.status_code == 404
    detail = r.json()["detail"]
    assert "study" in detail and "work" in detail
