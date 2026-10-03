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
import threading
from contextlib import asynccontextmanager

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from citations import _normalize_source
from config import (
    DEFAULT_TOP_K,
    SERVE_HOST, SERVE_PORT, SERVE_TOKEN_ENV,
    SERVE_MAX_TOP_K, SERVE_MAX_CONTEXT_CHARS, SERVE_USE_HYDE,
)
from pipeline import _format_context
from retrieval import hybrid_search
from vectorstore import list_documents, list_projects

logger = logging.getLogger(__name__)

_LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")

# One search at a time: the embedder and reranker are shared singletons on one GPU.
_SEARCH_LOCK = threading.Lock()

_NO_MATCH = "No matching content found in the ingested documents for this query."


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


def _resolve_scope(
    project: str | None, document: str | None,
) -> tuple[str | None, str | None]:
    """Validate the requested scope and return it in stored spelling.

    Anything unknown is a 404 that lists the valid names. Returning an empty
    result instead would let the model answer "the material does not cover this"
    about a typo (the F25 failure in ``pipeline``)."""
    if project is not None:
        projects = list_projects()
        resolved = _resolve_name(project, projects)
        if resolved is None:
            raise HTTPException(
                status_code=404,
                detail=f"Project '{project}' not found. Available projects: {projects}",
            )
        project = resolved
    if document is not None:
        docs = list_documents(project=project)
        resolved = _resolve_name(document, docs)
        if resolved is None:
            scope = f" in project '{project}'" if project else ""
            raise HTTPException(
                status_code=404,
                detail=f"Document '{document}' not found{scope}. Available documents: {docs}",
            )
        document = resolved
    return project, document


def _fit_chunks(chunks: list[dict], max_chars: int) -> list[dict]:
    """Longest rank-ordered prefix whose formatted context fits ``max_chars``.

    Whole passages only: a passage is never cut mid-text, so a citation header is
    never separated from its body. The top passage is always kept."""
    kept: list[dict] = []
    for chunk in chunks:
        if kept and len(_format_context(kept + [chunk])) > max_chars:
            break
        kept.append(chunk)
    return kept


# ── Schemas ──────────────────────────────────────────────────────────


class SearchRequest(BaseModel):
    query: str = Field(
        ..., min_length=1,
        description="What to look for, phrased as a question or a topic.",
    )
    project: str | None = Field(
        None, description="Restrict the search to one project. Omit to search every project.",
    )
    document: str | None = Field(
        None,
        description="Restrict the search to one document, by its name from "
                    "list_documents. Omit to search every document.",
    )
    top_k: int = Field(
        DEFAULT_TOP_K, description=f"How many passages to return (1-{SERVE_MAX_TOP_K}).",
    )


class SearchResponse(BaseModel):
    context: str
    chunks: int
    truncated: bool
    message: str | None = None


class DocumentsResponse(BaseModel):
    projects: dict[str, list[str]]


_SEARCH_DESCRIPTION = (
    "Search the user's ingested study documents (PDF, DOCX, XLSX) and return the "
    "most relevant passages. Use this whenever the user asks about their documents "
    "or course material. Each passage begins with a header of the form "
    "[source name, page N] or [source name, pages N-M]. Answer only from the "
    "returned passages and cite each fact with that exact bracket header. If the "
    "passages do not cover the question, search again with a different query before "
    "saying the material does not cover it. Call list_documents to learn valid "
    "`project` and `document` names."
)

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

    @app.post(
        "/search_documents",
        operation_id="search_documents",
        response_model=SearchResponse,
        dependencies=[Depends(require_token)],
        summary="Search the user's ingested documents",
        description=_SEARCH_DESCRIPTION,
    )
    def search_documents(req: SearchRequest) -> SearchResponse:
        project, document = _resolve_scope(req.project, req.document)
        top_k = max(1, min(req.top_k, SERVE_MAX_TOP_K))
        with _SEARCH_LOCK:
            chunks = hybrid_search(
                req.query, top_k=top_k, source=document, project=project,
                use_hyde=SERVE_USE_HYDE,
            )
        if not chunks:
            return SearchResponse(context="", chunks=0, truncated=False, message=_NO_MATCH)
        kept = _fit_chunks(chunks, SERVE_MAX_CONTEXT_CHARS)
        return SearchResponse(
            context=_format_context(kept),
            chunks=len(kept),
            truncated=len(kept) < len(chunks),
        )

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
