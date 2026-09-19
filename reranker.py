"""Cross-encoder reranker stage.

Cross-encoders score (query, candidate) pairs jointly, which is much more
accurate than dense-only similarity but too expensive to run on a whole corpus.
The standard pattern: pull ~50 cheap candidates with embeddings + BM25, rerank
the top 30 with a cross-encoder, return the top 10.
"""

from sentence_transformers import CrossEncoder
from config import (
    RERANKER_MODEL, RERANK_MAX_LENGTH, RERANK_BATCH_SIZE, RERANK_INPUT_CHAR_BUDGET,
)

_reranker: CrossEncoder | None = None


def get_reranker() -> CrossEncoder:
    """Lazy-load the reranker. ~600MB download on first use."""
    global _reranker
    if _reranker is None:
        _reranker = CrossEncoder(RERANKER_MODEL, max_length=RERANK_MAX_LENGTH)
    return _reranker


def rerank(query: str, candidates: list[dict], top_k: int = 10) -> list[dict]:
    """Score (query, candidate.text) pairs with a cross-encoder. Returns top_k sorted desc.

    Each candidate's text is pre-truncated to RERANK_INPUT_CHAR_BUDGET before pairing.
    The model already truncates at RERANK_MAX_LENGTH tokens, so this changes nothing
    about what gets scored — it just avoids tokenizing the full 6000-char chunk on
    every pair, which is the bulk of the CPU cost at this stage.
    """
    if not candidates:
        return []

    pairs = [(query, (c["text"] or "")[:RERANK_INPUT_CHAR_BUDGET]) for c in candidates]
    scores = get_reranker().predict(
        pairs, batch_size=RERANK_BATCH_SIZE, show_progress_bar=False,
    )

    scored = []
    for c, s in zip(candidates, scores):
        c2 = dict(c)
        c2["rerank_score"] = float(s)
        scored.append(c2)

    scored.sort(key=lambda c: c["rerank_score"], reverse=True)
    return scored[:top_k]
