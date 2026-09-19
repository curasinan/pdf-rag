import os
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"

# ── PDF chunking ─────────────────────────────────────────────────────
CHUNK_SIZE_CHARS = 6000       # ~1500 tokens per chunk
CHUNK_OVERLAP_CHARS = 800     # ~200 tokens overlap
MIN_CHUNK_CHARS = 1500        # never close a chunk smaller than this. With section-
                              # aware chunking from docling, lots of small sub-headings
                              # would otherwise produce chunks of <100 chars (poor for
                              # retrieval). The chunker honors section boundaries only
                              # once the current chunk has reached this size.

# ── Chunker version (used for cache invalidation) ────────────────────
# Bump this any time chunking output changes shape (different splitter, different
# size, different backend like docling). The Phase 3 cache checks file SHA-256
# along with this version and EMBEDDING_MODEL — change either constant and ingest
# will automatically reprocess every doc.
CHUNKER_VERSION = 4  # v4: project-namespaced, full-text-hashed chunk IDs with
                     # duplicate disambiguation (fixes F01 prefix-collision data
                     # loss and F02 cross-project ID theft). Re-ingest required —
                     # the cache key includes this version, so the next ingest of
                     # each doc rewrites its IDs from the legacy {source}::chunk_N /
                     # {source}::{prefix-hash} format to {project}::{source}::{hash}.
                     # v3: stable, content-derived chunk IDs (Weekend-3 Phase A2).
                     # See vectorstore.stable_chunk_id and the book's Case F.1
                     # ("Index Rebuild Improves Recall but Breaks Citations").
                     # v2: docling backend for PDF, section-aware splitting.

# ── PDF backend ──────────────────────────────────────────────────────
# True → docling for PDFs (preserves tables as markdown, headings, layout).
# False → fall back to PyMuPDF text-only extraction.
# DOCX and XLSX always use python-docx / openpyxl regardless.
USE_DOCLING = True

# ── OCR fallback ─────────────────────────────────────────────────────
# Defensive: when a PDF page extracts less than OCR_MIN_PAGE_CHARS of text via the
# normal backend, fall through to easyocr on that page only. The current corpus
# has no scanned PDFs so this rarely triggers, but it lets future image-only
# corpora work without extra setup. First call to easyocr downloads ~500 MB of
# detection + recognition models into the easyocr cache.
USE_OCR_FALLBACK = True
OCR_MIN_PAGE_CHARS = 50

# ── Embedding (BGE-M3: 1024 dims, 8192 max tokens, multilingual) ─────
EMBEDDING_MODEL = "BAAI/bge-m3"
EMBED_BATCH_SIZE = 12         # smaller batch since BGE-M3 is much bigger than MiniLM
EMBED_MAX_LENGTH = 1024       # cap input tokens per chunk for speed

# ── Reranker (cross-encoder; loads ~600MB lazily on first rerank) ────
RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"
RERANK_MAX_LENGTH = 512        # cross-encoder input token cap. NOTE: this is far
                               # below CHUNK_SIZE_CHARS (6000 chars ≈ 1500 tokens),
                               # so the reranker only scores roughly the first third
                               # of a full-size chunk. Facts in the tail of a long
                               # chunk are findable by BM25 but demoted here. Keep
                               # chunks focused, or raise this (model supports 8192)
                               # at a latency cost, if tail-of-chunk recall matters.
RERANK_BATCH_SIZE = 16         # pairs scored per CrossEncoder.predict batch.
RERANK_INPUT_CHAR_BUDGET = 3000  # pre-truncate each candidate's text to this many
                               # chars before pairing. The model truncates at
                               # RERANK_MAX_LENGTH tokens (~1500-2000 chars) anyway,
                               # so this is a safe superset that avoids tokenizing
                               # the full 6000-char chunk on every pair — a large CPU
                               # win with no change to what actually gets scored.

# ── ChromaDB (v2 path because BGE-M3 is 1024-dim, MiniLM was 384) ────
CHROMA_PERSIST_DIR = str(DATA_DIR / "chroma_v2")
COLLECTION_NAME = "documents"

# ── Project scoping ──────────────────────────────────────────────────
# Every chunk carries a `project` metadata field so multiple study domains can
# coexist in one ChromaDB without a query in domain A returning chunks from B.
# All CLI commands accept --project; if omitted we use DEFAULT_PROJECT.
DEFAULT_PROJECT = "default"

# ── BM25 ─────────────────────────────────────────────────────────────
BM25_INDEX_PATH = str(DATA_DIR / "bm25.pkl")

# ── Hybrid retrieval ─────────────────────────────────────────────────
RETRIEVAL_CANDIDATES = 50     # candidates pulled per channel (dense / BM25)
RERANK_TOP_N = 30             # how many fused candidates feed the reranker. Measured
                              # cost on this machine: reranking 50 full-size chunks
                              # took ~86s on CPU (the old "<2s" estimate was wrong by
                              # ~40x). 30 candidates + RERANK_INPUT_CHAR_BUDGET
                              # pre-truncation + RERANK_BATCH_SIZE batching brings a
                              # query's rerank stage back to a usable range. The
                              # per-source floor (MIN_PER_SOURCE) still has a 30-deep
                              # pool, which is plenty for detail chunks. Raise cautiously
                              # and re-benchmark if you do.
RRF_K = 60                    # standard RRF damping constant
DEFAULT_TOP_K = 10            # final results returned to the LLM
MIN_PER_SOURCE = 2            # per-source floor in cross-doc retrieval. If a source
                              # contributes any chunk to the top-K, ensure at least
                              # this many of its chunks are included (when available).
                              # Set to 1 to disable. Helps "give me everything from
                              # X" queries where one chunk wins ranking but others
                              # carry the rest of the answer.

# ── HyDE (Hypothetical Document Embeddings) ──────────────────────────
USE_HYDE = True               # Generate a hypothetical answer per query, embed it,
                              # and use as a third retrieval channel (RRF-fused with
                              # original query dense + BM25). Adds ~3-5s per query
                              # (one Sonnet CLI call). Skipped automatically for
                              # very short queries and exact-match lookups.
HYDE_MIN_QUERY_WORDS = 5      # Skip HyDE on queries shorter than this (lookup-style
                              # queries are hurt, not helped, by hallucinated context).

# ── Bridge backend: CLI (plan limits) or SDK (metered API) ───────────
# The CLI stays the default so "plan limits, not the paid API" remains the
# shipped contract. `PDFRAG_BRIDGE=sdk` opts a process into the SDK path, which
# ALSO requires PDFRAG_ALLOW_API_KEY=1 — a backend switch must never be able to
# silently start a metered bill.
BRIDGE_BACKEND = os.environ.get("PDFRAG_BRIDGE", "cli")

# CLI aliases are NOT valid API model IDs; every SDK call maps through this.
# Verified against the claude-api skill (cached 2026-06-24), not from memory.
MODEL_IDS = {
    "sonnet": "claude-sonnet-5",
    "opus": "claude-opus-5",
    "haiku": "claude-haiku-4-5",
}

SDK_MAX_RETRIES = 3
SDK_MAX_TOKENS = 16_000
MAX_CONTEXT_TOKENS = 37_500     # token twin of MAX_CONTEXT_CHARS (chars // 4)

# `temperature` is REJECTED (HTTP 400) by claude-opus-5 and claude-sonnet-5 —
# sampling parameters were removed from the Opus 4.7 generation onward. The
# project convention of passing temperature=0.0 on verifier calls therefore
# records INTENT only; the SDK path must drop it before the request. Determinism
# is not purchasable on these models, and pretending otherwise would 400 every
# judge call. See claude_bridge._call_sdk.
SDK_DROPS_TEMPERATURE = True

# ── Claude Code CLI (uses your plan limits, not the paid API) ────────
CLAUDE_MODEL_FAST = "sonnet"
CLAUDE_MODEL_QUALITY = "opus"
MAX_CONTEXT_CHARS = 150_000   # safe limit for Claude input
CHUNKS_PER_BATCH = 4          # chunks per map-phase call

# ── Citation claim support ───────────────────────────────────────────
# Measures "does the cited chunk actually contain this claim". Distinct from
# `citation_page_accuracy_avg`, which only asks "is this a real source and a
# page you were shown" — a fabrication check. Both are reported; neither
# replaces the other. See CLAUDE.md "Known Limitations" for what it cannot see.
CITATION_SUPPORT_ENABLED = True
CITATION_SUPPORT_MODEL = CLAUDE_MODEL_FAST
CITATION_SUPPORT_RUNS = 1          # 1 while iterating; 3 for a quoted/baseline run
CITATION_SUPPORT_MAX_PARTS = 8     # decomposition cap; bounds granularity drift
CITATION_CLAIM_MAX_CHARS = 600     # claim window cap, taken from the RIGHT (nearest marker)
CITATION_CLAIM_MIN_ALNUM = 12      # below this the citation joins the previous one as a
                                   # co-citation. Answers write back-to-back markers
                                   # (`…[Doc A, page 3][Doc B, pages 1-3]`); the second
                                   # marker's window is empty and must not score 0.
CITATION_MIN_CLAIM_TOKENS = 3      # fewer content tokens than this -> ABSTAIN, never 0.0

# Quote verification is NOT an exact-substring test. docling physically reorders
# text: both of h17's correct verbatim quotes are absent as substrings from their
# own correct source chunk, so a strict check demotes a citation that is right.
# Measured token recall of those quotes: 1.000 against the correct chunk, 0.375
# and 0.700 against the wrong one, 0.182 for a fabricated control. Hence 0.80.
CITATION_QUOTE_MIN_TOKEN_RECALL = 0.80
CITATION_QUOTE_RARE_DF_FRACTION = 0.25   # a token is "rare" if df <= 25% of chunks; the
                                         # rarest one must be present, so a quote cannot
                                         # pass on function words alone
CITATION_SUPPORT_CACHE_DIR = str(DATA_DIR / "citation_support_cache")
CITATION_SUPPORT_PROMPT_VERSION = 1      # bump on ANY prompt edit — it is part of the
                                         # cache key, so a stale verdict cannot replay
