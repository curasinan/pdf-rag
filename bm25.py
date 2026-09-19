"""BM25 keyword index over the chunks stored in ChromaDB.

The index is rebuilt from ChromaDB whenever the corpus signature changes
(chunk count + last id), and pickled to disk so cold starts stay fast.
"""

import logging
import os
import pickle
import re
from rank_bm25 import BM25Okapi

from config import BM25_INDEX_PATH
from vectorstore import get_all_chunks

logger = logging.getLogger(__name__)


# ── Module state (in-process cache) ──────────────────────────────────
# (bm25_obj, list_of_chunk_dicts, signature)
_state: tuple | None = None


# ── Helpers ──────────────────────────────────────────────────────────


def _tokenize(text: str) -> list[str]:
    """Cheap word tokenizer: lowercase, alphanumeric runs. Good default for English + code."""
    return re.findall(r"\w+", text.lower())


def _signature(chunks: list[dict]) -> tuple:
    """Cheap fingerprint to decide whether to rebuild the index."""
    if not chunks:
        return (0, None)
    return (len(chunks), chunks[-1]["id"])


def _save(state: tuple) -> None:
    os.makedirs(os.path.dirname(BM25_INDEX_PATH), exist_ok=True)
    try:
        with open(BM25_INDEX_PATH, "wb") as f:
            pickle.dump(state, f, protocol=pickle.HIGHEST_PROTOCOL)
    except OSError:
        # Persistence is a best-effort optimization, not a correctness requirement
        pass


def _load() -> tuple | None:
    if not os.path.exists(BM25_INDEX_PATH):
        return None
    try:
        with open(BM25_INDEX_PATH, "rb") as f:
            return pickle.load(f)
    except Exception:
        return None


# ── Public API ───────────────────────────────────────────────────────


def get_index():
    """Return (BM25Okapi, chunks, signature) or None if the corpus is empty.
    Rebuilds when ChromaDB has changed since the cached signature."""
    global _state

    chunks = get_all_chunks()
    sig = _signature(chunks)

    if _state is not None and _state[2] == sig:
        logger.debug("bm25 cache hit (in-memory): %d chunks", len(chunks))
        return _state

    cached = _load()
    if cached is not None and cached[2] == sig:
        logger.debug("bm25 cache hit (disk): %d chunks", len(chunks))
        _state = cached
        return _state

    if not chunks:
        _state = None
        return None

    logger.info("bm25 rebuilding index (%d chunks)", len(chunks))
    tokenized = [_tokenize(c["text"]) for c in chunks]
    bm25 = BM25Okapi(tokenized)
    _state = (bm25, chunks, sig)
    _save(_state)
    return _state


def invalidate() -> None:
    """Drop the cached index. Call after ingest or delete."""
    global _state
    _state = None
    if os.path.exists(BM25_INDEX_PATH):
        try:
            os.remove(BM25_INDEX_PATH)
        except OSError:
            pass


def query_bm25(
    query: str,
    n_results: int = 50,
    source: str | None = None,
    project: str | None = None,
) -> list[dict]:
    """Top-k chunks by BM25 score, optionally filtered by source and/or project.

    The BM25 index covers the whole collection; per-project filtering happens after
    scoring. This keeps the index global (no per-project rebuilds) while still
    isolating queries to a project's chunks."""
    state = get_index()
    if state is None:
        return []
    bm25, chunks, _ = state

    scores = bm25.get_scores(_tokenize(query))

    def keep(c: dict) -> bool:
        if source is not None and c["source"] != source:
            return False
        if project is not None and c.get("project") != project:
            return False
        return True

    candidates = [(i, scores[i]) for i, c in enumerate(chunks) if keep(c)]
    candidates.sort(key=lambda x: x[1], reverse=True)

    out = []
    for i, score in candidates[:n_results]:
        if score <= 0:
            continue  # no keyword overlap; skip noise
        c = chunks[i]
        out.append({
            "id": c["id"],
            "text": c["text"],
            "pages": c["pages"],
            "source": c["source"],
            "project": c.get("project"),
            "bm25_score": float(score),
        })
    return out
