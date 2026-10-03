#!/usr/bin/env python3
"""OpenAPI tool server — exposes hybrid retrieval to a locally served model.

Usage:
    python tool_server.py                                   # loopback only, no auth
    PDFRAG_SERVER_TOKEN=<token> python tool_server.py --host 0.0.0.0

Why this exists: Open WebUI (or any OpenAPI tool client) registers this server as
a tool. The model calls ``search_documents`` when a question needs the ingested
material and writes the answer itself — nothing here calls Claude. Retrieval is
the same ``hybrid_search`` every ``rag.py`` command uses, and passages are
formatted by ``pipeline._format_context``, so the model sees the same
``[source, page N]`` headers the rest of the project parses as citations.

Every OpenAPI operation becomes a tool the model sees, so the schema is kept to
exactly two operations; ``/health`` is excluded from it.

Ingest stays a CLI step. This process holds the vector index in memory, so after
``rag.py ingest`` / ``batch_ingest.py`` the server must be restarted.
"""

import hmac
import logging
import os
import sys
from contextlib import asynccontextmanager

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from citations import _normalize_source
from config import SERVE_HOST, SERVE_PORT, SERVE_TOKEN_ENV
from vectorstore import list_documents, list_projects

logger = logging.getLogger(__name__)

_LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")


# ── Startup guards ───────────────────────────────────────────────────


def check_bind(host: str, token: str | None) -> None:
    """Refuse a network-reachable bind that has no token (fail closed).

    Reaching this server from a Docker container needs a non-loopback bind, which
    also makes it reachable from the rest of the network. Without a token that
    publishes every ingested document to anyone who can connect."""
    if host not in _LOOPBACK_HOSTS and not token:
        raise ValueError(
            f"Refusing to listen on {host} without {SERVE_TOKEN_ENV} set: that would "
            "expose every ingested document to the network unauthenticated."
        )


def _warm() -> None:
    """Load the embedder, reranker and BM25 index before the first tool call.

    Without this the first search pays for a cold model load, which is long
    enough for a tool client to time out. Also the one place that says which
    device retrieval landed on — a CPU-only torch build is silent otherwise."""
    import bm25
    from embeddings import get_model
    from reranker import get_reranker

    device = str(get_model().device)
    get_reranker()
    state = bm25.get_index()
    chunks = len(state[1]) if state else 0
    logger.info("tool server ready: device=%s, %d chunks indexed", device, chunks)
    if not device.startswith("cuda"):
        logger.warning(
            "retrieval models are on '%s', not a GPU. If this machine has one, torch "
            "was installed without CUDA support; expect slow reranking.", device,
        )
    if chunks == 0:
        logger.warning("no documents are ingested yet; every search will come back empty.")


# ── Name resolution ──────────────────────────────────────────────────


def _resolve_name(name: str, stored: list[str]) -> str | None:
    """Stored spelling of ``name``, or None when it matches nothing.

    Stored names keep the document's own punctuation and Unicode form (curly
    apostrophes, NFD accents); a model retypes them in ASCII / NFC. Match exactly
    first, then on ``citations._normalize_source`` — the same folding the citation
    checker uses — but only when that is unambiguous."""
    if name in stored:
        return name
    wanted = _normalize_source(name)
    matches = [s for s in stored if _normalize_source(s) == wanted]
    return matches[0] if len(matches) == 1 else None


# ── Schemas ──────────────────────────────────────────────────────────


class DocumentsResponse(BaseModel):
    projects: dict[str, list[str]]


_LIST_DESCRIPTION = (
    "List the user's ingested documents, grouped by project. Use this to learn the "
    "exact `project` and `document` names that search_documents accepts."
)


# ── App factory ──────────────────────────────────────────────────────


def create_app(token: str | None = None, warm: bool = True) -> FastAPI:
    """Build the app. ``token=None`` disables auth (loopback use only — see
    ``check_bind``). ``warm=False`` skips model loading, for tests."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if warm:
            _warm()
        yield

    app = FastAPI(
        title="PDF RAG document search",
        version="1.0.0",
        description="Search the user's ingested study documents and list what is ingested.",
        lifespan=lifespan,
    )
    bearer = HTTPBearer(auto_error=False)

    def require_token(
        request: Request,
        creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    ) -> None:
        if not token:
            return
        supplied = creds.credentials if creds else ""
        if not hmac.compare_digest(supplied.encode("utf-8"), token.encode("utf-8")):
            # Log the path, never the credential.
            logger.warning("rejected request to %s: missing or invalid bearer token",
                           request.url.path)
            raise HTTPException(
                status_code=401,
                detail="Missing or invalid bearer token.",
                headers={"WWW-Authenticate": "Bearer"},
            )

    @app.get("/health", include_in_schema=False)
    def health() -> dict:
        return {"status": "ok"}

    @app.get(
        "/list_documents",
        operation_id="list_documents",
        response_model=DocumentsResponse,
        dependencies=[Depends(require_token)],
        summary="List the user's ingested documents",
        description=_LIST_DESCRIPTION,
    )
    def list_documents_tool(project: str | None = None) -> DocumentsResponse:
        projects = list_projects()
        if project is not None:
            resolved = _resolve_name(project, projects)
            if resolved is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Project '{project}' not found. Available projects: {projects}",
                )
            projects = [resolved]
        return DocumentsResponse(
            projects={p: list_documents(project=p) for p in projects}
        )

    return app
