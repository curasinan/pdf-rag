"""HyDE (Hypothetical Document Embeddings) — query rewriting for retrieval.

Idea
====
A user query like "what does the document say about break-even formulas" doesn't
look much like the actual passages in the corpus, which contain phrases like
"break-even = fixed costs divided by gross margin". The query embedding lives
far from the answer embeddings.

HyDE asks the LLM to write a brief plausible answer to the query — even if
fabricated — and embeds THAT. The fake answer's vector is much closer in
embedding space to the real answer chunks than the question's vector is.

We don't use the fake answer as text. We only use its embedding as a third
retrieval channel, RRF-fused with the original-query dense and BM25 channels.

Skip rules
==========
HyDE actively hurts short / exact-match queries. `should_use_hyde` filters those
out so we don't waste a Sonnet call on "find foo" or "what page is X on".
"""

import logging

from claude_bridge import call_claude
from config import CLAUDE_MODEL_FAST, HYDE_MIN_QUERY_WORDS
from prompts import HYDE_SYSTEM, HYDE_USER

logger = logging.getLogger(__name__)


_LOOKUP_PREFIXES = (
    "find ",
    "locate ",
    "where is ",
    "what page",
    "on which page",
    "on what page",
)


def should_use_hyde(query: str) -> bool:
    """Heuristic: skip HyDE on short queries, exact-match queries, and page lookups.

    These query shapes prefer literal token match (BM25) over semantic expansion;
    a hallucinated context just dilutes the signal.
    """
    if not query:
        return False
    if len(query.split()) < HYDE_MIN_QUERY_WORDS:
        return False
    if '"' in query:        # quoted phrase → user wants literal match
        return False
    low = query.lower().lstrip()
    if low.startswith(_LOOKUP_PREFIXES):
        return False
    return True


def generate_hypothetical_answer(query: str) -> str:
    """Single Sonnet CLI call. ~3-5s. Returns a short fake passage.

    The output is consumed by the embedder, never shown to the user. If the
    Claude call hard-fails, we let the exception propagate up; the caller can
    fall back to non-HyDE retrieval.
    """
    text = call_claude(
        CLAUDE_MODEL_FAST,
        HYDE_SYSTEM,
        HYDE_USER.format(query=query),
    )
    logger.debug("hyde: generated %d chars for query=%r", len(text), query[:80])
    return text
