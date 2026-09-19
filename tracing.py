"""Per-query trace records (Weekend-3 Phase A1).

Why this exists
===============
The book "RAG Evaluation & Testing in Production" treats the trace record as the
foundation of every other capability: regression diffs, oracle-context experiments,
canary comparisons, drift detection, and the failure gallery all replay from
traces. Without a structured persisted record per query, you cannot reproduce a
failure, cannot diff two pipeline versions, and cannot link a production
complaint back to evidence.

What we record
==============
For each query we capture (Appendix A.1):
    - query_id, query_text
    - retrieved_chunks: list of {doc_id, chunk_id, rank, score, source, pages, text_hash}
    - reranked_chunks: list of chunk IDs in final order
    - hyde_used: bool (was HyDE active for this query)
    - answer
    - parsed_citations: list of {source, page} extracted from the answer
    - citation_validation: per-citation existence + match results
    - versions: model, prompt_hash, embedding_model, chunker_version, reranker
    - telemetry: latency_ms, tokens_in, tokens_out (best-effort estimates)

Persistence layout
==================
Traces are written to data/traces/YYYY-MM-DD/{query_id}.json. One file per query
keeps the directory grep-friendly and lets the failure gallery cherry-pick traces
without loading a giant aggregate file.

Usage
=====
    from tracing import RagTrace, persist_trace, hash_text, prompt_hash

    trace = RagTrace(
        query_id="h01",
        query_text="What is KPI #5?",
        retrieved_chunks=[...],
        reranked_chunks=[...],
        hyde_used=True,
        answer=answer_text,
        parsed_citations=[...],
        citation_validation={...},
        versions={
            "model": "opus",
            "prompt_hash": prompt_hash(QA_SYSTEM, QA_USER),
            "embedding_model": EMBEDDING_MODEL,
            "chunker_version": CHUNKER_VERSION,
            "reranker": RERANKER_MODEL,
        },
        telemetry={"latency_ms": 8200, "tokens_in": 4400, "tokens_out": 1200},
    )
    persist_trace(trace)

The harness in eval/run.py and any production query path can both call
persist_trace; the same record format makes diffing and replay trivial.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
import logging
import re
import textwrap
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent
TRACE_DIR = ROOT / "data" / "traces"


# ── Hashing helpers ──────────────────────────────────────────────────


def hash_text(text: str) -> str:
    """SHA-1 first 12 hex chars of UTF-8 encoded text. Used for chunk text hashes
    in trace records so we can detect when the chunk text drifted under the same ID
    (Case F.1 in the book: chunk IDs reused across re-chunking)."""
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:12]


def prompt_hash(*parts: str) -> str:
    """Hash the concatenation of all prompt strings (system + user template, etc.).
    Bumping any prompt string changes this hash, which the regression CI gate can
    use to invalidate cached eval results."""
    h = hashlib.sha1()
    for p in parts:
        h.update((p or "").encode("utf-8"))
        h.update(b"\x00")  # separator so concat collisions are impossible
    return h.hexdigest()[:12]


def normalized_source(fn) -> str:
    """A function's source with comments, formatting and docstrings removed.

    Raw source is the wrong input to a comparability hash in both directions. This
    repo documents WHY at length — the judge functions are roughly three-quarters
    prose by volume — so hashing raw text fires on a wording fix, and a gate that
    cries wolf gets ignored, which is the same end state as no gate. Round-tripping
    through the AST keeps only what changes behaviour.

    It also makes the hash insensitive to line endings for free: eval/run.py is 100%
    CRLF on this machine, so a byte hash would move on a checkout with different
    newline handling. ``ast.unparse`` always emits ``\\n``.

    Not free of assumptions: ``ast.unparse`` output is a CPython implementation
    detail, so a Python upgrade can move the hash without any edit. That is
    tolerable only because the consumer WARNS and never fails — see
    ``eval/gate.py``.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef,
                                 ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = node.body
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            node.body = body[1:] or [ast.Pass()]
    return ast.unparse(tree)


def _code_fingerprint(obj) -> str:
    """One symbol's contribution to :func:`code_hash`, dispatched on type.

    Every branch exists because the obvious shortcut is wrong somewhere:

    - ``re.Pattern`` carries its flags separately, so ``.pattern`` alone is
      **flag-blind** — ``re.compile(p, re.IGNORECASE)`` and ``re.compile(p)`` share
      a pattern string and differ only in ``.flags`` (34 vs 32). Dropping
      IGNORECASE would change matching with the hash unmoved.
    - ``set`` / ``frozenset`` MUST be sorted. Python randomizes string hashing per
      process, so ``repr()`` of a set of strings differs between runs; left
      unsorted the hash would never be stable and the warning would fire forever.
    - Ordered sequences keep their order, because order is meaningful (the
      first-match scan over ``_NEGATIVE_PHRASES``).

    Unknown types RAISE rather than being skipped. A silently skipped symbol is
    precisely the blindness this hash exists to remove.
    """
    if inspect.isfunction(obj) or inspect.ismethod(obj):
        return "fn:" + normalized_source(obj)
    if isinstance(obj, re.Pattern):
        return f"re:{obj.pattern}\x00{obj.flags}"
    if isinstance(obj, (set, frozenset)):
        return "set:" + "\x00".join(sorted(repr(x) for x in obj))
    if isinstance(obj, (tuple, list)):
        return "seq:" + "\x00".join(repr(x) for x in obj)
    if obj is None or isinstance(obj, (str, bytes, bool, int, float)):
        return "val:" + repr(obj)
    raise TypeError(
        f"code_hash: no fingerprint rule for {type(obj).__name__}. Add an explicit "
        f"branch — skipping the symbol would reintroduce exactly the blindness this "
        f"hash exists to remove."
    )


def code_hash(named_objects) -> str:
    """Hash the BEHAVIOUR-BEARING code of a set of ``(name, object)`` pairs.

    The twin of :func:`prompt_hash` for logic that is not a prompt string. Pairs are
    sorted by name, so reordering the registry does not move the hash; only editing
    a symbol does.
    """
    h = hashlib.sha1()
    for name, obj in sorted(named_objects, key=lambda pair: pair[0]):
        h.update(name.encode("utf-8"))
        h.update(b"\x00")
        h.update(_code_fingerprint(obj).encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:12]


# ── Dataclass ────────────────────────────────────────────────────────


@dataclass
class RagTrace:
    """One trace record per query. Mirrors Appendix A.1 of the book.

    All fields except `query_id`, `query_text`, and `answer` have safe defaults so
    a partial trace from a failure path still serializes."""

    query_id: str
    query_text: str
    retrieved_chunks: list[dict] = field(default_factory=list)
    reranked_chunks: list[str] = field(default_factory=list)
    hyde_used: bool = False
    answer: str = ""
    parsed_citations: list[dict] = field(default_factory=list)
    citation_validation: dict = field(default_factory=dict)
    versions: dict = field(default_factory=dict)
    telemetry: dict = field(default_factory=dict)
    timestamp_utc: str = ""

    def to_dict(self) -> dict:
        if not self.timestamp_utc:
            self.timestamp_utc = datetime.now(timezone.utc).isoformat()
        return asdict(self)


# ── Persistence ──────────────────────────────────────────────────────


def _today_dir() -> Path:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d = TRACE_DIR / today
    d.mkdir(parents=True, exist_ok=True)
    return d


def persist_trace(trace: RagTrace, subdir: str | None = None) -> Path:
    """Write a trace JSON to data/traces/{date or subdir}/{query_id}.json.

    Returns the file path. If a trace with the same query_id already exists for
    this date, it is overwritten (the eval harness re-runs the same questions, so
    the latest run wins). For longitudinal comparisons, pass `subdir` like
    "eval_2026-04-30_run1" to namespace runs."""
    if subdir:
        d = TRACE_DIR / subdir
        d.mkdir(parents=True, exist_ok=True)
    else:
        d = _today_dir()
    out = d / f"{trace.query_id}.json"
    out.write_text(
        json.dumps(trace.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return out


def load_trace(path: Path | str) -> dict:
    """Read a trace file. Returned as a dict (not a RagTrace) so old records with
    extra fields don't blow up dataclass construction."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def list_traces(subdir: str | None = None) -> list[Path]:
    """List all trace files in a given subdir (or today). Sorted by name."""
    d = TRACE_DIR / subdir if subdir else _today_dir()
    if not d.exists():
        return []
    return sorted(d.glob("*.json"))


# ── Convenience builder for retrieval results ────────────────────────


def make_retrieved_records(chunks: list[dict]) -> list[dict]:
    """Convert raw retrieval output (list of chunk dicts) to the trace schema.

    Each output record has: doc_id (== source), chunk_id, rank, score, source,
    pages, text_hash. Missing scores survive as None; missing text becomes empty
    string with empty hash. Robust to the slightly different field names dense vs
    BM25 vs reranker emit."""
    out = []
    for rank, c in enumerate(chunks, start=1):
        text = c.get("text", "") or ""
        score = c.get("rerank_score")
        if score is None:
            score = c.get("rrf_score")
        if score is None:
            score = c.get("bm25_score")
        if score is None and c.get("distance") is not None:
            # Convert cosine distance to a similarity-style score so log readers
            # don't have to remember which is which.
            score = 1.0 - float(c["distance"])
        out.append({
            "doc_id": c.get("source", "?"),
            "chunk_id": c.get("id") or c.get("chunk_id"),
            "rank": rank,
            "score": float(score) if score is not None else None,
            "source": c.get("source", "?"),
            "pages": c.get("pages"),
            "text_hash": hash_text(text),
        })
    return out
