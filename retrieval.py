"""Hybrid retrieval pipeline: dense + BM25, fused with RRF, then cross-encoder reranked.

Flow per query:
    1. Embed the query with BGE-M3.
    2. Pull RETRIEVAL_CANDIDATES from ChromaDB (cosine).
    3. Pull RETRIEVAL_CANDIDATES from BM25 (keywords).
    4. Reciprocal Rank Fusion merges the two lists into one ranking.
    5. Take RERANK_TOP_N from the fused list and rerank with a cross-encoder.
    6. Return the final top_k.

Why this beats the old pure-dense pipeline:
    - BM25 catches exact-match queries (acronyms, citations, code identifiers, equations)
      that dense embeddings often miss.
    - RRF is rank-based, so it's robust to the wildly different score scales of cosine
      and BM25 — no normalization or hand-tuned weights needed.
    - The reranker reads the query and chunk together, so it can score relevance the
      way dense retrieval cannot.
"""

import logging
from collections import OrderedDict

from embeddings import embed_texts
from vectorstore import query_dense
from bm25 import query_bm25
from reranker import rerank
from hyde import generate_hypothetical_answer, should_use_hyde
from claude_bridge import ClaudeCLIError
from config import (
    RETRIEVAL_CANDIDATES,
    RERANK_TOP_N,
    RRF_K,
    DEFAULT_TOP_K,
    MIN_PER_SOURCE,
    USE_HYDE,
)

logger = logging.getLogger(__name__)


def reciprocal_rank_fusion(rankings: list[list[dict]], k: int = RRF_K) -> list[dict]:
    """Merge multiple ranked lists into one. Score = sum of 1 / (k + rank) across lists.

    Standard RRF (Cormack et al. 2009). k=60 is the conventional default and works well
    in practice; lowering k weights top ranks more, raising k flattens the curve.
    """
    rrf_scores: dict[str, float] = {}
    chunk_map: dict[str, dict] = {}

    for ranking in rankings:
        for rank, chunk in enumerate(ranking):
            cid = chunk["id"]
            rrf_scores[cid] = rrf_scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
            if cid not in chunk_map:
                chunk_map[cid] = chunk

    fused = []
    for cid, score in rrf_scores.items():
        c = dict(chunk_map[cid])
        c["rrf_score"] = score
        fused.append(c)

    fused.sort(key=lambda c: c["rrf_score"], reverse=True)
    return fused


def _score_of(c: dict) -> float:
    return c.get("rerank_score", c.get("rrf_score", 0.0))


def _chunk_key(c: dict):
    """Stable identity for dedup across the reranked list and the fusion pool."""
    return c.get("id") or id(c)


def _tier_sort_key(c: dict):
    """Reranked chunks (tier 1, ordered by cross-encoder score) always precede
    promotion-only chunks (tier 0, ordered by RRF score). The two score scales
    aren't comparable, so we never interleave them — a promoted detail chunk is
    included but ranked below everything the cross-encoder actually scored."""
    if "rerank_score" in c:
        return (1, c["rerank_score"])
    return (0, c.get("rrf_score", 0.0))


def apply_min_per_source(
    ranked: list[dict],
    top_k: int,
    min_per_source: int,
    promotion_pool: list[dict] | None = None,
) -> list[dict]:
    """Guarantee a per-source *floor* on the final top-K without capping any source.

    This is a floor, not a quota cap. It starts from the pure relevance winners
    (``ranked[:top_k]``) and only *promotes* extra chunks to satisfy the floor for
    sources that already earned a slot. A source whose chunks legitimately occupy
    8 of the top 10 keeps all 8 — the earlier implementation capped every source
    at ``min_per_source`` and displaced top-ranked chunks with rank-30+ chunks
    from unrelated sources (finding F03).

    Why the floor exists: dense + BM25 + rerank can rank the "headline" chunk of a
    document very high while leaving its detail chunks just outside top-K. "List
    the 5 KPIs in document X" then gets only the headline. The floor pulls a
    source's next-best chunk(s) in when it made the cut but its detail is outside
    top-K.

    ``promotion_pool`` (the full fused list) lets the floor reach detail chunks
    that were NOT reranked — the reranker only scores ``ranked``'s shallow pool for
    latency (finding F20), but a source's second chunk can sit deeper in fusion.
    Promoted chunks carry only an ``rrf_score`` and are ranked below every
    cross-encoder-scored chunk. Defaults to ``ranked`` when not supplied.

    Floor conflicts (top_k too small for every base source's floor) are resolved
    by PRIORITY EVICTION, best-source-first: a promotion evicts the lowest-scored
    chunk of a source that is over its own floor; failing that, the lowest chunk
    of a strictly worse-ranked source. A source never loses a slot to a
    worse-ranked source's floor, so the F03 pathology (rank-40 chunks from
    unrelated sources displacing the winner's detail chunks) cannot recur.

    Set min_per_source=1 to disable (returns ranked[:top_k]).
    """
    if not ranked or min_per_source <= 1:
        return ranked[:top_k]

    pool = promotion_pool if promotion_pool is not None else ranked

    # Per source, an ordered, deduped candidate list: reranked chunks first (best
    # relevance signal), then any additional chunks from the fusion pool.
    cand_by_source: OrderedDict[str, list[dict]] = OrderedDict()
    seen_per_source: dict[str, set] = {}
    for c in list(ranked) + list(pool):
        s = c.get("source", "?")
        seen = seen_per_source.setdefault(s, set())
        key = _chunk_key(c)
        if key in seen:
            continue
        seen.add(key)
        cand_by_source.setdefault(s, []).append(c)

    result = list(ranked[:top_k])
    result_keys = {_chunk_key(c) for c in result}
    counts: dict[str, int] = {}
    for c in result:
        s = c.get("source", "?")
        counts[s] = counts.get(s, 0) + 1

    # Sources that earned a slot in the natural top-k, best-rank first. Their rank
    # here is their floor priority.
    base_sources: list[str] = []
    for c in ranked[:top_k]:
        s = c.get("source", "?")
        if s not in base_sources:
            base_sources.append(s)
    priority = {s: i for i, s in enumerate(base_sources)}  # lower = better

    for s in base_sources:
        avail = cand_by_source.get(s, [])
        target = min(min_per_source, len(avail))
        for c in avail:
            if counts.get(s, 0) >= target:
                break
            key = _chunk_key(c)
            if key in result_keys:
                continue
            if len(result) < top_k:
                # Free slot — no eviction needed.
                result.append(c)
                result_keys.add(key)
                counts[s] = counts.get(s, 0) + 1
                continue
            # Pick an eviction victim. Preference 1: the lowest-scored chunk of a
            # source that is over its own floor (it stays at/above floor after).
            over_floor = [
                v for v in result
                if v.get("source", "?") != s
                and counts.get(v.get("source", "?"), 0) > min_per_source
            ]
            if over_floor:
                victim = min(over_floor, key=_score_of)
            else:
                # Preference 2: the lowest chunk of a strictly WORSE-ranked source
                # (its floor loses to this source's floor). Never evict from a
                # better-ranked source.
                worse = [
                    v for v in result
                    if priority.get(v.get("source", "?"), len(priority)) > priority[s]
                ]
                if not worse:
                    break  # no legitimate victim — this floor can't be satisfied
                victim = max(
                    worse,
                    key=lambda v: (priority.get(v.get("source", "?"), len(priority)),
                                   -_score_of(v)),
                )
            result.remove(victim)
            result_keys.discard(_chunk_key(victim))
            vs = victim.get("source", "?")
            counts[vs] = counts.get(vs, 0) - 1
            result.append(c)
            result_keys.add(key)
            counts[s] = counts.get(s, 0) + 1

    result.sort(key=_tier_sort_key, reverse=True)
    return result[:top_k]


def hybrid_search(
    query: str,
    top_k: int = DEFAULT_TOP_K,
    source: str | None = None,
    project: str | None = None,
    use_rerank: bool = True,
    min_per_source: int = MIN_PER_SOURCE,
    use_hyde: bool = USE_HYDE,
) -> list[dict]:
    """End-to-end retrieval. Pass source=<doc_name> to scope a single document,
    project=<name> to scope a single project (multi-project isolation).

    `min_per_source` enforces a per-source floor in cross-doc results (default from
    config). Pass 1 to disable. Has no effect when `source` is set (single-doc
    queries don't need a quota).

    `use_hyde` toggles the HyDE third channel (default from config). Skipped
    automatically for short / lookup-style queries via `should_use_hyde`.
    """
    logger.debug(
        "hybrid_search: query=%r source=%r project=%r top_k=%d use_rerank=%s min_per_source=%d use_hyde=%s",
        query[:80], source, project, top_k, use_rerank, min_per_source, use_hyde,
    )
    q_vec = embed_texts([query])[0]

    dense_q = query_dense(q_vec, n_results=RETRIEVAL_CANDIDATES, source=source, project=project)
    sparse = query_bm25(query, n_results=RETRIEVAL_CANDIDATES, source=source, project=project)

    # Optional third channel: HyDE-rewritten query embedding.
    dense_h: list[dict] = []
    hyde_used = False
    if use_hyde and should_use_hyde(query):
        try:
            hyde_text = generate_hypothetical_answer(query)
            h_vec = embed_texts([hyde_text])[0]
            dense_h = query_dense(h_vec, n_results=RETRIEVAL_CANDIDATES, source=source, project=project)
            hyde_used = True
            logger.debug("  hyde channel: %d candidates", len(dense_h))
        except ClaudeCLIError:
            # Claude CLI failure during HyDE shouldn't kill the whole query.
            logger.warning("HyDE generation failed; falling back to non-HyDE retrieval.")
        except Exception as e:
            logger.warning("HyDE error (%s); falling back to non-HyDE retrieval.", e)

    logger.debug(
        "  candidates: dense_q=%d %s sparse=%d",
        len(dense_q),
        f"dense_hyde={len(dense_h)}" if hyde_used else "(hyde skipped)",
        len(sparse),
    )

    rankings = [r for r in (dense_q, dense_h, sparse) if r]
    if not rankings:
        logger.debug("  no candidates; returning empty")
        return []

    # Always run RRF, even for a single channel: it guarantees every fused chunk
    # carries an rrf_score. Without it, the single-channel path (BM25 empty + HyDE
    # skipped) returned score-less dicts and the downstream floor/sort collapsed to
    # source-grouped insertion order instead of relevance order (finding F43). RRF
    # over one list preserves that list's order.
    fused = reciprocal_rank_fusion(rankings)
    logger.debug("  fused=%d", len(fused))

    if use_rerank and fused:
        # Rerank the top RERANK_TOP_N fused candidates (not literally all — the
        # fused list can exceed RERANK_TOP_N once channels disagree). Then apply the
        # per-source floor and trim to top_k.
        reranked = rerank(query, fused[:RERANK_TOP_N], top_k=RERANK_TOP_N)
        logger.debug("  reranked=%d", len(reranked))
        if source is not None:
            return reranked[:top_k]
        # The full fused list is the promotion pool: the floor can pull a source's
        # detail chunk from beyond the (deliberately shallow) rerank window.
        result = apply_min_per_source(reranked, top_k, min_per_source, promotion_pool=fused)
        logger.debug("  after quota=%d", len(result))
        return result

    if source is not None:
        return fused[:top_k]
    result = apply_min_per_source(fused, top_k, min_per_source)
    logger.debug("  after quota=%d (no rerank)", len(result))
    return result
