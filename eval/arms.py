"""Answer producers — the one seam where the ablation arms differ.

Everything downstream of :meth:`AnswerProducer.produce` in ``eval/run.py``
(citation validation, judging, verdict mapping, tracing, aggregation, reporting)
is arm-agnostic and must stay that way. Adding a fourth arm means adding a class
here and a line in :func:`make_producer`, and touching nothing else.

Arms
====
``A`` — hybrid RAG (status quo): dense + BM25 + RRF + cross-encoder rerank, top-k
        chunks as context. Byte-identical in behaviour to the pre-refactor code.
``B`` — whole corpus in one prompt (Phase 2).
``C`` — agentic file search over a plain-text mirror (Phase 2).

Why ``retrieval_applicable`` exists
===================================
It is the field that keeps the comparison honest. Recall / MRR / nDCG are
*ranking* metrics. If a non-ranking arm's context chunks flow into them, arm B
(which holds the whole corpus) scores a trivially perfect "100% retrieval
recall" and an MRR determined by nothing but sort order — numbers that are
meaningless but would sit in the comparison table looking authoritative. Only a
producer that actually ranks may declare these metrics applicable.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from claude_bridge import (                                   # noqa: E402
    AGENTIC_TOOLS, AgenticSandboxError, ClaudeCLIError, SessionLimitError,
    assert_agentic_sandbox, call_claude_agentic, call_claude_json,
    total_input_tokens,
)

#: Bumped when the telemetry a producer records changes. Part of every arm's
#: config hash, so answers cached before the change are regenerated rather than
#: replayed with fields missing — a cost table with holes in it is worse than one
#: that costs a few extra calls to fill.
TELEMETRY_VERSION = 2
from config import (                                          # noqa: E402
    CLAUDE_MODEL_QUALITY, CHUNKER_VERSION, EMBEDDING_MODEL, RERANKER_MODEL,
    USE_HYDE, RRF_K, RERANK_TOP_N, MIN_PER_SOURCE,
)
from pipeline import _call_claude, _format_context            # noqa: E402
from prompts import QA_SYSTEM, QA_USER                        # noqa: E402
from retrieval import hybrid_search                           # noqa: E402


# ── Producer contract ────────────────────────────────────────────────


@dataclass
class Production:
    """One arm's answer to one question, plus everything the harness needs.

    ``context_chunks`` entries must carry ``text`` — ``pipeline._format_context``
    subscripts it directly (``chunk['text']``), unlike every other consumer which
    uses ``.get()``. ``source``/``pages``/``id`` are optional but required for any
    metric computed from them to be meaningful.
    """

    answer: str
    context_chunks: list[dict] = field(default_factory=list)
    evidence_text: str = ""
    telemetry: dict = field(default_factory=dict)
    retrieval_applicable: bool = False
    citation_scope: str = "own"      # "own" | "corpus_only"
    error: str | None = None         # set → ERROR record; never cached
    fatal: bool = False              # set → abort the run (quota / auth), do not score


def _sha12(*parts) -> str:
    blob = json.dumps(parts, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]


def _usage_telemetry(envelope: dict) -> dict:
    """Cost/latency fields common to every arm, from a CLI JSON envelope."""
    usage = (envelope or {}).get("usage") or {}
    return {
        "num_turns": (envelope or {}).get("num_turns"),
        "duration_ms": (envelope or {}).get("duration_ms"),
        "duration_api_ms": (envelope or {}).get("duration_api_ms"),
        "cost_usd": (envelope or {}).get("total_cost_usd"),
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "cache_read_input_tokens": usage.get("cache_read_input_tokens"),
        "cache_creation_input_tokens": usage.get("cache_creation_input_tokens"),
        # The only input figure safe to put in a cost table.
        "total_input_tokens": total_input_tokens(usage),
    }


# ── Arm A — hybrid RAG (status quo) ──────────────────────────────────


class ArmAHybridRAG:
    """The current pipeline, unchanged: hybrid_search → _format_context → Opus.

    Split into timed retrieval and generation phases because arm A's CPU
    cross-encoder rerank dominates its latency (measured ~86s for 50 candidates
    on this machine before RERANK_TOP_N dropped to 30). Reporting one blended
    number would misattribute where the cost actually goes.
    """

    name = "A_hybrid_rag"
    label = "A"

    def __init__(self, project: str, top_k: int, use_rerank: bool = True):
        self.project = project
        self.top_k = top_k
        self.use_rerank = use_rerank

    def config_hash(self) -> str:
        # use_rerank is IN the hash deliberately. The answer cache is keyed on this,
        # so without it a --no-rerank run would replay the reranked run's answers and
        # the A/B would measure nothing while looking perfectly healthy — the same
        # cache-blindness that made a separate --cache-dir load-bearing for seed 2.
        return _sha12(
            self.top_k, self.project, CHUNKER_VERSION, EMBEDDING_MODEL,
            RERANKER_MODEL, USE_HYDE, RRF_K, RERANK_TOP_N, MIN_PER_SOURCE,
            TELEMETRY_VERSION, self.use_rerank,
        )

    def produce(self, question: str, qtype: str, qid: str) -> Production:
        t0 = time.time()
        try:
            chunks = hybrid_search(question, top_k=self.top_k, project=self.project,
                                   use_rerank=self.use_rerank)
        except Exception as e:                                   # retrieval is local; any failure is real
            return Production(answer="", error=f"retrieval: {e}")
        t_ret = time.time() - t0

        evidence = _format_context(chunks)

        t1 = time.time()
        try:
            answer, envelope = call_claude_json(
                CLAUDE_MODEL_QUALITY,
                QA_SYSTEM,
                QA_USER.format(context=evidence, question=question),
            )
        except SessionLimitError as e:
            return Production(
                answer="", context_chunks=chunks, evidence_text=evidence,
                retrieval_applicable=True, error=f"generation: {e}", fatal=True,
            )
        except ClaudeCLIError as e:
            return Production(
                answer="", context_chunks=chunks, evidence_text=evidence,
                retrieval_applicable=True, error=f"generation: {e}",
            )

        return Production(
            answer=answer,
            context_chunks=chunks,
            evidence_text=evidence,
            retrieval_applicable=True,
            telemetry={
                "retrieval_wall_s": round(t_ret, 2),
                "generation_wall_s": round(time.time() - t1, 2),
                "n_context_chunks": len(chunks),
                "evidence_chars": len(evidence),
                **_usage_telemetry(envelope),
            },
        )


# ── Arm B — the whole corpus in one prompt ───────────────────────────


#: A real asymmetry, included deliberately and disclosed rather than hidden:
#: arm A's prompt cannot honestly claim completeness, and the negative questions
#: ("do any of the materials discuss X?") are only answerable by a model that
#: believes it has everything.
ARM_B_PREAMBLE = (
    "The following is the COMPLETE set of source documents "
    "({n_sources} documents, {n_chunks} sections). Nothing has been omitted, "
    "retrieved, or filtered.\n\n---\n\n"
)

#: Tripwire, not a budget. The corpus measures ~286K chars (~75-105K tokens)
#: against a 200K-token window, so it fits with room to spare — but if the corpus
#: ever outgrows the window, arm B must fail loudly rather than silently answer
#: from a truncated corpus.
ARM_B_CEILING_CHARS = 600_000


def build_full_corpus_context(project: str) -> tuple[str, list[dict], dict]:
    """Render every chunk in the project as one context block.

    Uses ``pipeline._format_context`` — the exact function arm A uses — so header
    grammar, page rendering via ``format_pages_human`` and the ``---`` separator
    are identical, and ``citations.parse_citations`` behaves the same for both
    arms. Arm A and arm B then differ in *nothing* but chunk count.

    Deliberately does NOT reuse ``compose_capstone.dump_corpus``: its per-chunk
    header is ``[Pages [1, 2, 3]]`` — no source name, and the raw-list shape F10
    removed — so arm B's citations would fail to parse and it would lose the
    citation metrics for a formatting reason. Its 200K default would also
    silently truncate 23 of 24 sources.
    """
    from vectorstore import get_all_chunks     # local import: keeps module import cheap

    chunks = get_all_chunks(project=project)
    if not chunks:
        raise ValueError(f"no chunks in project {project!r}; ingest before running arm B")

    def _seq(c):
        s = c.get("chunk_seq")
        return s if isinstance(s, int) else 0

    chunks.sort(key=lambda c: (unicodedata.normalize("NFC", c.get("source", "")), _seq(c)))

    body = _format_context(chunks)
    n_sources = len({c.get("source") for c in chunks})
    context = ARM_B_PREAMBLE.format(n_sources=n_sources, n_chunks=len(chunks)) + body

    if len(context) > ARM_B_CEILING_CHARS:
        raise ValueError(
            f"arm B context is {len(context):,} chars, above the "
            f"{ARM_B_CEILING_CHARS:,} tripwire — the corpus may no longer fit in "
            "one prompt. Re-evaluate whether arm B is still feasible; do NOT "
            "truncate, which would fabricate the result."
        )

    meta = {
        "n_chunks": len(chunks),
        "n_sources": n_sources,
        "chars": len(context),
        "est_tokens_chars_div_4": len(context) // 4,
        "sha1": hashlib.sha1(context.encode("utf-8")).hexdigest(),
    }
    return context, chunks, meta


class ArmBFullContext:
    """No retrieval: the entire corpus is the context, every question.

    Cost note for the writeup: arm B makes the *fewest* LLM calls of any arm
    (no HyDE, no judge difference) but consumes by far the most input tokens —
    ~25 x ~90K. That inversion is itself a finding.
    """

    name = "B_full_context"
    label = "B"

    def __init__(self, project: str, top_k: int):
        self.project = project
        self.top_k = top_k          # unused; kept so the registry stays uniform
        self._context = None
        self._chunks = None
        self._meta = None

    def _ensure_context(self):
        if self._context is None:
            self._context, self._chunks, self._meta = build_full_corpus_context(self.project)
            print(
                f"  arm B context: {self._meta['chars']:,} chars, "
                f"{self._meta['n_chunks']} chunks, {self._meta['n_sources']} sources, "
                f"sha1={self._meta['sha1'][:12]} (no truncation)"
            )
        return self._context, self._chunks, self._meta

    def config_hash(self) -> str:
        # The corpus IS the configuration. Hash it (never key by 286K of text).
        _, _, meta = self._ensure_context()
        return _sha12("B", meta["sha1"], CHUNKER_VERSION, TELEMETRY_VERSION)

    def produce(self, question: str, qtype: str, qid: str) -> Production:
        context, chunks, meta = self._ensure_context()
        t0 = time.time()
        try:
            answer, envelope = call_claude_json(
                CLAUDE_MODEL_QUALITY,
                QA_SYSTEM,                                  # byte-identical to arm A
                QA_USER.format(context=context, question=question),
            )
        except SessionLimitError as e:
            return Production(answer="", context_chunks=chunks, evidence_text=context,
                              error=f"generation: {e}", fatal=True)
        except ClaudeCLIError as e:
            return Production(answer="", context_chunks=chunks, evidence_text=context,
                              error=f"generation: {e}")

        return Production(
            answer=answer,
            context_chunks=chunks,
            evidence_text=context,
            retrieval_applicable=False,        # holds everything; ranking metrics are meaningless
            telemetry={
                "generation_wall_s": round(time.time() - t0, 2),
                "n_context_chunks": len(chunks),
                "evidence_chars": len(context),
                "corpus_sha1": meta["sha1"],
                **_usage_telemetry(envelope),
            },
        )


# ── Arm C — agentic file search ──────────────────────────────────────


ARM_C_SYSTEM_SUFFIX = QA_SYSTEM + (
    "\n\nThe documents are plain-text files in your working directory, one per "
    "source. Each begins with a line '# SOURCE: <canonical name>', and pages are "
    "delimited by lines of the form '=== PAGE N ==='. Cite using the canonical "
    "name from the '# SOURCE:' header and the page number of the '=== PAGE N ===' "
    "block the text came from — for example [Why Do Coffee Shops Fail, page 25]. "
    "Read _INDEX.md first to see what is available. Use at most about 15 tool "
    "calls. Answer only from these files."
)

#: Arm C's user prompt is QA_USER with the context block removed, so the tail the
#: model sees ("Question: ... / Answer (cite page numbers):") is identical across
#: all three arms.
ARM_C_USER = "Question: {question}\n\nAnswer (cite page numbers):"


class ArmCAgenticFiles:
    """Claude with read-only file tools over a plain-text mirror, no vector store.

    The mirror is mandatory — see tools/build_mirror.py for the empirical reason
    (Read fails on every source file on this machine; Grep on PDFs returns zero
    hits for text that demonstrably exists).
    """

    name = "C_agentic_files"
    label = "C"

    def __init__(self, project: str, top_k: int, mirror_dir=None, timeout: int = 1800,
                 max_budget_usd: float | None = None, output_format: str = "json"):
        self.project = project
        self.top_k = top_k
        self.timeout = timeout
        self.max_budget_usd = max_budget_usd
        self.output_format = output_format
        if mirror_dir is None:
            from tools.build_mirror import default_mirror_dir
            mirror_dir = default_mirror_dir()
        self.mirror_dir = Path(mirror_dir)
        self._manifest = None

    def _ensure_mirror(self) -> dict:
        if self._manifest is None:
            manifest_path = self.mirror_dir / "_manifest.json"
            if not manifest_path.exists():
                raise ValueError(
                    f"no corpus mirror at {self.mirror_dir}. "
                    "Build it first: python tools/build_mirror.py"
                )
            self._manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            # Fail closed before any question runs, not midway through.
            assert_agentic_sandbox(self.mirror_dir, ROOT)
        return self._manifest

    def config_hash(self) -> str:
        manifest = self._ensure_mirror()
        mirror_sha = _sha12(sorted((k, v["sha1"]) for k, v in manifest.items()))
        return _sha12("C", mirror_sha, ARM_C_SYSTEM_SUFFIX, tuple(AGENTIC_TOOLS),
                      self.output_format, TELEMETRY_VERSION)

    def produce(self, question: str, qtype: str, qid: str) -> Production:
        self._ensure_mirror()
        t0 = time.time()
        try:
            answer, envelope = call_claude_agentic(
                CLAUDE_MODEL_QUALITY,
                ARM_C_SYSTEM_SUFFIX,
                ARM_C_USER.format(question=question),
                work_dir=self.mirror_dir,
                repo_root=ROOT,
                timeout=self.timeout,
                output_format=self.output_format,
                max_budget_usd=self.max_budget_usd,
            )
        except SessionLimitError as e:
            return Production(answer="", citation_scope="corpus_only",
                              error=f"agentic: {e}", fatal=True)
        except (ClaudeCLIError, AgenticSandboxError) as e:
            return Production(answer="", citation_scope="corpus_only",
                              error=f"agentic: {e}")

        return Production(
            answer=answer,
            context_chunks=[],                 # no chunk set; citations validate corpus-wide
            evidence_text="",                  # nothing was "shown" to the model
            retrieval_applicable=False,
            citation_scope="corpus_only",
            telemetry={
                "generation_wall_s": round(time.time() - t0, 2),
                "permission_denials": envelope.get("permission_denials"),
                "session_id": envelope.get("session_id"),
                **_usage_telemetry(envelope),
            },
        )


# ── Registry ─────────────────────────────────────────────────────────


_ARMS = {
    "A": ArmAHybridRAG,
    "B": ArmBFullContext,
    "C": ArmCAgenticFiles,
}


def make_producer(arm: str, *, project: str, top_k: int, **kw):
    """Build the producer for ``arm``."""
    arm = (arm or "A").upper()
    if arm not in _ARMS:
        raise ValueError(f"unknown arm {arm!r}; available: {sorted(_ARMS)}")
    cls = _ARMS[arm]
    if cls is ArmCAgenticFiles:
        return cls(
            project=project, top_k=top_k,
            mirror_dir=kw.get("mirror_dir"),
            timeout=kw.get("agentic_timeout", 1800),
            max_budget_usd=kw.get("max_budget_usd"),
            output_format=kw.get("agentic_output_format", "json"),
        )
    if cls is ArmAHybridRAG:
        return cls(project=project, top_k=top_k, use_rerank=kw.get("use_rerank", True))
    return cls(project=project, top_k=top_k)
