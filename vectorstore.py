"""Single-collection ChromaDB vector store.

All chunks live in one collection, scoped by `source` and `project` metadata.
This scales to many documents without paying the O(docs * n_results) cost the
old per-document collection design had, and lets multiple study projects
coexist in one DB without leaking into each other's queries.
"""

import hashlib
import logging
import chromadb
from config import (
    CHROMA_PERSIST_DIR, COLLECTION_NAME, DEFAULT_PROJECT,
    CHUNKER_VERSION, EMBEDDING_MODEL,
)

logger = logging.getLogger(__name__)


# ── Stable chunk IDs (Weekend-3 Phase A2, hardened in v4) ────────────
# Why: the book (Case F.1 "Index Rebuild Improves Recall but Breaks Citations")
# warns that sequential chunk IDs ({source}::chunk_0, ::chunk_1, ...) shift
# meaning every time the chunker output changes. After re-chunking, citation
# resolvers that pointed at chunk_4 now point at a different paragraph silently.
#
# Fix: derive the chunk ID from a hash of its text, so the ID is a stable
# property of the *content* rather than the position. Different text produces a
# different ID, so stale citations explicitly miss instead of silently pointing
# at the wrong content.
#
# Two bugs the v4 format fixes (see the July-2026 design review):
#   F01 — the old code hashed only text[:512] of a ≤6000-char chunk, so two
#         chunks sharing a boilerplate prefix (repeated table headers, per-page
#         letterhead) collided. Colliding IDs in one upsert batch raise
#         DuplicateIDError *after* replace_document already deleted the old
#         chunks, wiping the document. We now hash the FULL text.
#   F02 — the ID had no project component, so ingesting the same source into a
#         second project upserted byte-identical IDs and silently flipped the
#         first project's chunks over to the new project. The project is now part
#         of the ID namespace, so the two copies coexist as ChromaDB promises.
#
# Format: {project}::{source}::{sha1(full_text)[:16]} — 16 hex chars give 64 bits
# of collision resistance. Genuinely identical chunk texts (rare, but possible for
# repeated boilerplate blocks) are disambiguated in add_chunks with a ::N suffix.

def stable_chunk_id(source: str, text: str, project: str = DEFAULT_PROJECT) -> str:
    """Compute a stable, content-derived, project-namespaced chunk ID."""
    h = hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:16]
    return f"{project}::{source}::{h}"

# ── Singletons ───────────────────────────────────────────────────────
_client: chromadb.ClientAPI | None = None
_collection = None


def _get_client() -> chromadb.ClientAPI:
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
    return _client


def get_collection():
    """Get or create the single 'documents' collection (cosine space)."""
    global _collection
    if _collection is None:
        _collection = _get_client().get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
    return _collection


# ── Where-clause helper ──────────────────────────────────────────────


def _build_where(source: str | None = None, project: str | None = None) -> dict | None:
    """Compose ChromaDB `where` filter from optional source / project predicates.

    Single predicate → flat dict (Chroma rejects $and on a single condition).
    Multiple predicates → wrapped in $and.
    No predicates → None (Chroma rejects empty dicts here).
    """
    parts: list[dict] = []
    if source is not None:
        parts.append({"source": source})
    if project is not None:
        parts.append({"project": project})
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    return {"$and": parts}


# ── Mutations ────────────────────────────────────────────────────────


def add_chunks(
    chunks: list[dict],
    embeddings: list[list[float]],
    project: str = DEFAULT_PROJECT,
    file_sha256: str | None = None,
):
    """Upsert chunks. IDs are namespaced by source so collisions across docs are impossible.
    Every chunk picks up:
      - `project` for multi-project isolation
      - `file_sha256`, `chunker_version`, `embedding_model` for the Phase 3 cache key
        (ingest can skip if all three match the stored values)
    """
    coll = get_collection()
    metas = []
    ids = []
    seen_ids: dict[str, int] = {}
    for c in chunks:
        # v4: ID is content-derived (stable across re-chunking) AND project-
        # namespaced (so the same source in two projects can't clobber each other).
        # The parser sequence number is kept in metadata under `chunk_seq`.
        cid = stable_chunk_id(c["source"], c["text"], project=project)
        # Disambiguate genuinely-identical chunk texts (repeated boilerplate) so a
        # true content collision can't drop a chunk or raise DuplicateIDError mid-
        # upsert. Deterministic: the Nth occurrence of a colliding hash gets ::N.
        if cid in seen_ids:
            seen_ids[cid] += 1
            logger.warning(
                "Duplicate chunk content in %r (project=%r); disambiguating id %s::%d",
                c["source"], project, cid, seen_ids[cid],
            )
            cid = f"{cid}::{seen_ids[cid]}"
        else:
            seen_ids[cid] = 0
        ids.append(cid)
        m = {
            "pages": str(c["pages"]),
            "source": c["source"],
            "chunk_id": cid,                      # stable, hash-based
            "chunk_seq": c["chunk_id"],           # original parser sequence number
            "project": project,
            "chunker_version": CHUNKER_VERSION,
            "embedding_model": EMBEDDING_MODEL,
        }
        if file_sha256 is not None:
            m["file_sha256"] = file_sha256
        metas.append(m)
    # Hard guarantee: no duplicate IDs reach ChromaDB (would raise DuplicateIDError
    # on chromadb>=0.5 and, on the delete-then-insert path, leave the doc absent).
    assert len(set(ids)) == len(ids), (
        f"add_chunks produced {len(ids) - len(set(ids))} duplicate IDs after "
        f"disambiguation — this should be impossible; refusing to upsert."
    )
    coll.upsert(
        ids=ids,
        embeddings=embeddings,
        documents=[c["text"] for c in chunks],
        metadatas=metas,
    )


def delete_document(source: str, project: str | None = None):
    """Remove every chunk belonging to a given source.

    When `project` is set the delete is scoped to that project — useful when the
    same source name was ingested into multiple projects. When omitted, every
    chunk for the source is removed regardless of project (matches old behavior)."""
    coll = get_collection()
    coll.delete(where=_build_where(source=source, project=project))


def replace_document(
    source: str,
    chunks: list[dict],
    embeddings: list[list[float]],
    project: str = DEFAULT_PROJECT,
    file_sha256: str | None = None,
):
    """Idempotent ingest: wipe any existing chunks for this (source, project), then insert
    fresh ones. Prevents orphaned chunks when a re-ingested doc has fewer chunks than before."""
    delete_document(source, project=project)
    add_chunks(chunks, embeddings, project=project, file_sha256=file_sha256)


def get_source_metadata(source: str, project: str | None = None) -> dict | None:
    """Return the cache-key triple (file_sha256, chunker_version, embedding_model) plus
    the chunk count for a source. Returns None if the source isn't ingested.

    All chunks for the same source carry the same triple, so reading any one is enough.
    """
    coll = get_collection()
    where = _build_where(source=source, project=project)
    if where is None:
        return None
    data = coll.get(where=where, limit=1, include=["metadatas"])
    if not data["ids"]:
        return None
    m = data["metadatas"][0]
    return {
        "file_sha256": m.get("file_sha256"),
        "chunker_version": m.get("chunker_version"),
        "embedding_model": m.get("embedding_model"),
    }


# ── Queries ──────────────────────────────────────────────────────────


def query_dense(
    query_embedding: list[float],
    n_results: int = 50,
    source: str | None = None,
    project: str | None = None,
) -> list[dict]:
    """Top-k by cosine similarity, optionally filtered by source and/or project."""
    coll = get_collection()
    if coll.count() == 0:
        return []
    where = _build_where(source=source, project=project)
    results = coll.query(
        query_embeddings=[query_embedding],
        n_results=min(n_results, coll.count()),
        where=where,
    )
    out = []
    for i in range(len(results["ids"][0])):
        meta = results["metadatas"][0][i]
        out.append({
            "id": results["ids"][0][i],
            "text": results["documents"][0][i],
            "pages": meta["pages"],
            "source": meta["source"],
            "project": meta.get("project", DEFAULT_PROJECT),
            "distance": results["distances"][0][i] if results["distances"] else None,
        })
    return out


def get_all_chunks(
    source: str | None = None,
    project: str | None = None,
) -> list[dict]:
    """Return every chunk (optionally filtered by source and/or project). Used to build BM25."""
    coll = get_collection()
    if coll.count() == 0:
        return []
    where = _build_where(source=source, project=project)
    data = coll.get(where=where, include=["documents", "metadatas"])
    out = []
    for i, doc_id in enumerate(data["ids"]):
        meta = data["metadatas"][i]
        out.append({
            "id": doc_id,
            "text": data["documents"][i],
            "pages": meta["pages"],
            "source": meta["source"],
            "project": meta.get("project", DEFAULT_PROJECT),
            "chunk_id": meta.get("chunk_id"),
            "chunk_seq": meta.get("chunk_seq"),
        })
    return out


def get_chunks_for_source(source: str, project: str | None = None) -> list[dict]:
    """All chunks for a single document, sorted by document-order (for summarize / map-reduce).

    After A2 the stable `chunk_id` is a hash, so it can no longer be used as a sort
    key. We sort by `chunk_seq` (the original parser sequence number) when present,
    falling back to int(chunk_id) for legacy chunks ingested before A2.
    """
    chunks = get_all_chunks(source=source, project=project)
    def _key(c):
        seq = c.get("chunk_seq")
        if seq is not None:
            try:
                return int(seq)
            except (TypeError, ValueError):
                pass
        # Legacy fallback: pre-A2 chunks have chunk_id as a numeric string
        cid = c.get("chunk_id")
        try:
            return int(cid) if cid is not None else 0
        except (TypeError, ValueError):
            return 0
    chunks.sort(key=_key)
    return chunks


def list_documents(project: str | None = None) -> list[str]:
    """Distinct source names currently ingested. When `project` is given, scoped to that
    project; otherwise all projects."""
    coll = get_collection()
    if coll.count() == 0:
        return []
    where = _build_where(project=project)
    metas = coll.get(where=where, include=["metadatas"])["metadatas"]
    return sorted({m["source"] for m in metas})


def list_projects() -> list[str]:
    """Distinct project names currently present in the collection."""
    coll = get_collection()
    if coll.count() == 0:
        return []
    metas = coll.get(include=["metadatas"])["metadatas"]
    return sorted({m.get("project", DEFAULT_PROJECT) for m in metas})


def count_chunks(source: str | None = None, project: str | None = None) -> int:
    coll = get_collection()
    where = _build_where(source=source, project=project)
    if where is None:
        return coll.count()
    return len(coll.get(where=where, include=[])["ids"])
