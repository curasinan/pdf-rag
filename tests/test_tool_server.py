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


def _chunk(source: str, pages: str, text: str) -> dict:
    return {"id": f"study::{source}::{pages}", "source": source, "pages": pages,
            "text": text, "project": "study"}


@pytest.fixture
def fake_store(monkeypatch):
    """Stub retrieval and the store lookups. The returned dict records the last
    search call; set ``fake_store["results"]`` to control what the search returns."""
    state: dict = {"results": [
        _chunk("docA", "[1, 2, 3]", "Alpha passage."),
        _chunk("docB", "[7]", "Beta passage."),
    ]}

    def fake_search(query, **kwargs):
        state["query"] = query
        state["kwargs"] = kwargs
        return list(state["results"])

    def fake_list_documents(project=None):
        if project is None:
            return sorted(d for docs in DOCS.values() for d in docs)
        return sorted(DOCS.get(project, []))

    monkeypatch.setattr(tool_server, "hybrid_search", fake_search)
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


# ── search_documents ────────────────────────────────────────────────


def test_search_requires_token(client):
    assert client.post("/search_documents", json={"query": "alpha"}).status_code == 401


def test_search_passes_scope_and_disables_hyde(client, fake_store):
    r = client.post("/search_documents", headers=AUTH, json={
        "query": "what is alpha", "project": "study", "document": "docA", "top_k": 5})
    assert r.status_code == 200
    assert fake_store["query"] == "what is alpha"
    assert fake_store["kwargs"] == {
        "top_k": 5, "source": "docA", "project": "study", "use_hyde": False}


def test_top_k_is_clamped_not_rejected(client, fake_store):
    """The caller is a model; a 422 for asking for 500 passages helps nobody."""
    client.post("/search_documents", headers=AUTH, json={"query": "x", "top_k": 500})
    assert fake_store["kwargs"]["top_k"] == tool_server.SERVE_MAX_TOP_K
    client.post("/search_documents", headers=AUTH, json={"query": "x", "top_k": 0})
    assert fake_store["kwargs"]["top_k"] == 1
    client.post("/search_documents", headers=AUTH, json={"query": "x"})
    assert fake_store["kwargs"]["top_k"] == tool_server.DEFAULT_TOP_K


def test_context_uses_pipeline_citation_headers(client):
    body = client.post("/search_documents", headers=AUTH, json={"query": "x"}).json()
    assert body == {
        "context": "[docA, pages 1-3]\nAlpha passage.\n\n---\n\n[docB, page 7]\nBeta passage.",
        "chunks": 2,
        "truncated": False,
        "message": None,
    }


def test_unknown_document_is_404_listing_valid_names(client, fake_store):
    """An empty result here would let the model say 'the material does not cover
    this' about a typo."""
    r = client.post("/search_documents", headers=AUTH,
                    json={"query": "x", "project": "study", "document": "docZ"})
    assert r.status_code == 404
    detail = r.json()["detail"]
    assert "docA" in detail and "docB" in detail
    assert "query" not in fake_store, "search must not run for an unknown document"


def test_unknown_project_is_404(client, fake_store):
    r = client.post("/search_documents", headers=AUTH,
                    json={"query": "x", "project": "nope"})
    assert r.status_code == 404
    assert "study" in r.json()["detail"]
    assert "query" not in fake_store


def test_document_name_resolves_across_typographic_punctuation(client, fake_store, monkeypatch):
    """Stored names keep the PDF's curly apostrophe; a model retypes it in ASCII.
    The filter must still hit, and must pass the STORED spelling downstream."""
    stored = "The Franchise\u2019s Plan"
    monkeypatch.setattr(tool_server, "list_documents", lambda project=None: [stored])
    r = client.post("/search_documents", headers=AUTH,
                    json={"query": "x", "document": "the franchise's plan"})
    assert r.status_code == 200
    assert fake_store["kwargs"]["source"] == stored


def test_empty_result_says_so(client, fake_store):
    fake_store["results"] = []
    body = client.post("/search_documents", headers=AUTH, json={"query": "x"}).json()
    assert body["chunks"] == 0 and body["context"] == ""
    assert "No matching content" in body["message"]


def test_context_cap_drops_whole_passages(client, fake_store, monkeypatch):
    """Each formatted passage is 115 chars, the separator 7: two fit in 250, three do not."""
    fake_store["results"] = [
        _chunk("docA", "[1]", "A" * 100),
        _chunk("docB", "[2]", "B" * 100),
        _chunk("docC", "[3]", "C" * 100),
    ]
    monkeypatch.setattr(tool_server, "SERVE_MAX_CONTEXT_CHARS", 250)
    body = client.post("/search_documents", headers=AUTH, json={"query": "x"}).json()
    assert body["chunks"] == 2 and body["truncated"] is True
    assert body["context"].endswith("B" * 100), "a passage was cut mid-text"
    assert "C" * 10 not in body["context"]

    monkeypatch.setattr(tool_server, "SERVE_MAX_CONTEXT_CHARS", 10)
    body = client.post("/search_documents", headers=AUTH, json={"query": "x"}).json()
    assert body["chunks"] == 1, "the top passage is always kept"
    assert body["context"].endswith("A" * 100)


def test_openapi_exposes_exactly_two_tools(client):
    """Open WebUI turns every operation into a tool the model sees."""
    spec = client.get("/openapi.json").json()
    ops = {op["operationId"] for path in spec["paths"].values() for op in path.values()}
    assert ops == {"search_documents", "list_documents"}
    assert "/health" not in spec["paths"]
