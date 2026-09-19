"""Eval harness (Weekend-3 upgrade).

What changed vs Weekend-2
=========================
- B1: Evidence-only judge prompts. The judge now sees retrieved EVIDENCE (top-k
  chunks) and is instructed to score the answer USING ONLY that evidence. Prior
  version compared expected_answer to actual_answer with no evidence; that lets
  judges score by paraphrase similarity instead of grounding.
- B2: Strict 5-axis JSON judge schema (relevance / groundedness / citation /
  critical_errors / short_rationale). Parser with 1 retry on parse failure.
- B3: Multi-run median (N=3 by default). Flip-rate per axis is reported. Single
  legacy verdict (EQUIVALENT / PARTIAL / DIFFERENT) is derived from the relevance
  score so existing dashboards keep working.
- C1: MRR@10 and nDCG@10 added per question and per bucket.
- A3: Citation parsing + validation on the model's actual answer (not just the
  retrieved set) — citation accuracy reported per question.
- A1: Each question writes a structured trace under data/traces/eval_<run_id>/.

Numeric / negative / page_lookup judges remain rule-based (cheap and stable).
The qa / synthesis types use the new evidence-only LLM judge.

Outputs
=======
    eval/results.json            (or eval/results_hard.json with --hard)
    eval/results.md              (or eval/results_hard.md with --hard)
    data/traces/eval_<id>/q*.json   (one per question)
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
import time
import unicodedata
import uuid
from pathlib import Path


# ── Imports / setup ──────────────────────────────────────────────────


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Retrieval and context formatting now live behind the arm producers
# (eval/arms.py) — the single seam where architectures differ.
from pipeline import _call_claude                                 # noqa: E402
from claude_bridge import ClaudeCLIError                          # noqa: E402
from config import (                                              # noqa: E402
    CLAUDE_MODEL_QUALITY, CLAUDE_MODEL_FAST,
    EMBEDDING_MODEL, RERANKER_MODEL, CHUNKER_VERSION,
    CITATION_SUPPORT_ENABLED, CITATION_SUPPORT_RUNS,
    CITATION_SUPPORT_CACHE_DIR, CITATION_SUPPORT_PROMPT_VERSION,
)
from prompts import QA_SYSTEM, QA_USER                            # noqa: E402
from citations import (                                           # noqa: E402
    parse_and_validate, parse_citations, parse_page_only_mentions, _expand_pages,
)
from tracing import (RagTrace, persist_trace, prompt_hash, code_hash,  # noqa: E402
                     make_retrieved_records)
from claude_bridge import SessionLimitError, AgenticSandboxError  # noqa: E402
from eval.arms import make_producer                               # noqa: E402
from eval.cache import AnswerCache, Checkpoint                    # noqa: E402


# ── Configuration ────────────────────────────────────────────────────


TOP_K = 10
EVAL_PROJECT = "capstone"

# B3: how many judge runs per question. The book's Chapter 7/10 reference is N=3
# with median aggregation. Override with --judge-runs.
DEFAULT_JUDGE_RUNS = 3

# Judge model. Sonnet by default (fast); upgrade to Opus on borderline (3.0)
# scores to implement Chapter 9 §9.1.3 tiered escalation.
JUDGE_MODEL_FAST = CLAUDE_MODEL_FAST
JUDGE_MODEL_STRONG = CLAUDE_MODEL_QUALITY


# ── B1 + B2: evidence-only judge prompt with strict JSON schema ──────


JUDGE_SYSTEM = (
    "You are a strict RAG evaluator. You score a candidate answer against retrieved "
    "evidence and a reference answer. Use ONLY the EVIDENCE block to judge whether "
    "the candidate's claims are supported. Ignore your outside knowledge. Penalize "
    "claims that are absent from the EVIDENCE. The reference answer is a minimal "
    "sufficient answer, NOT a ceiling: additional detail that IS present in the "
    "EVIDENCE is not an error, and length alone is never a critical error. "
    "Reply with a single JSON object, nothing else, no code fences, no preamble."
)

JUDGE_USER = """Question:
{question}

EVIDENCE (retrieved chunks the model was shown — score using ONLY this):
{evidence}

Reference answer (what the user expected):
{expected}

Candidate answer (from the system being evaluated):
{candidate}

Score the candidate on these axes (1-5 integers; higher is better):
- relevance: does the answer satisfy the user's intent? Is it correct, complete, on-scope?
- groundedness: are factual claims supported by the EVIDENCE block? Penalize claims not in evidence.
- citation_accuracy: EVIDENCE chunks are labelled with the page RANGE they span
  (e.g. "[Doc Name, pages 24-25]") because one chunk covers several pages, and adjacent
  chunks share a boundary page by construction. A citation is CORRECT when the
  (source, page-range) it names is that of an EVIDENCE chunk whose text contains the
  content it is attached to. Do NOT penalize a range for being wider than the reference
  answer's pages, for overlapping another cited range, or for differing from the
  reference's page numbers — the reference is not the citation standard, the EVIDENCE
  headers are. Use 5 if no citations are needed (e.g. negative questions).
- critical_errors: categorical defects only. A matter of degree (too long, too detailed,
  a debatable interpretation, a citation that is correct but coarser than you would
  prefer) belongs on the axes above and is NOT a critical error. Emit a label ONLY if its
  definition is literally met:
    HALLUCINATION  - states a FACT that appears nowhere in the EVIDENCE. Content present
                     in the EVIDENCE but absent from the reference answer is NOT a
                     hallucination. A comparison, inference or summary drawn from evidence
                     the candidate cites is NOT a hallucination; if you think it
                     overreaches, lower groundedness instead.
    CITATION_WRONG - attributes content to a (source, page-range) whose EVIDENCE chunk
                     does not contain it.
    WRONG_EVIDENCE - asserts a value or fact the EVIDENCE contradicts.
    FORMAT_FAIL    - does not answer the question asked at all.
    REFUSAL_ERROR  - refuses although the EVIDENCE answers the question.
    OVER_REFUSAL   - hedges so heavily it withholds an answer the EVIDENCE supports.
    NONE           - no categorical defect.
  For every label you emit you MUST supply "quote": a 5-25 word span copied
  CHARACTER-FOR-CHARACTER from the Candidate answer above that contains the defect. If you
  cannot copy such a span out of the Candidate answer, do not emit the label. Quote the
  CANDIDATE, never the reference answer and never the EVIDENCE.
- short_rationale: one sentence explaining the lowest-scoring axis.

Output exactly this JSON:
{{"relevance":<1-5>,"groundedness":<1-5>,"citation_accuracy":<1-5>,"critical_errors":[{{"label":"<LABEL>","quote":"<verbatim span from the Candidate answer>"}}],"short_rationale":"<one sentence>"}}
Use [{{"label":"NONE","quote":""}}] when there is no critical error."""


# Map relevance score → legacy verdict so old dashboards keep working.
def _verdict_from_relevance(rel: int | float) -> str:
    if rel is None:
        return "ERROR"
    if rel >= 4:
        return "EQUIVALENT"
    if rel >= 3:
        return "PARTIAL"
    if rel >= 1:
        return "DIFFERENT"
    return "ERROR"


# ── Parsing the judge's JSON output ──────────────────────────────────


_VALID_ERRORS = {
    "HALLUCINATION", "CITATION_WRONG", "WRONG_EVIDENCE",
    "FORMAT_FAIL", "REFUSAL_ERROR", "OVER_REFUSAL", "NONE",
}

# A judge rationale is the only record of *why* a run flagged something. Storage is
# 15 LLM-judged questions x 3 runs, so the old 300-char cap bought nothing and cost
# the audit trail.
_MAX_RATIONALE_CHARS = 1200


def _parse_judge_json(raw: str) -> dict | None:
    """Best-effort JSON parse. Returns None if it can't recover a valid object."""
    if not raw:
        return None
    text = raw.strip()
    # Strip code fences if the model added them despite instructions
    if text.startswith("```"):
        # remove first line + trailing fence
        parts = text.split("\n", 1)
        text = parts[1] if len(parts) > 1 else ""
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    # First try direct parse
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Fallback: extract first {...} block
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    # Coerce / validate fields
    try:
        rel = int(data["relevance"])
        gnd = int(data["groundedness"])
        cit = int(data["citation_accuracy"])
    except (KeyError, ValueError, TypeError):
        return None
    # Two accepted shapes. Current rubric asks for {"label", "quote"} objects so a
    # vote can be checked against the answer it accuses; bare label strings are the
    # legacy shape and still parse, so stored per_run rows re-aggregate unchanged.
    raw_errs = data.get("critical_errors", []) or []
    if not isinstance(raw_errs, list):
        raw_errs = [raw_errs]
    pairs: list[list[str]] = []
    for e in raw_errs:
        if isinstance(e, dict):
            label = str(e.get("label", "")).upper().strip()
            quote = str(e.get("quote", "") or "")
        else:
            label, quote = str(e).upper().strip(), ""
        if label in _VALID_ERRORS and label != "NONE":
            pairs.append([label, quote])
    errs = sorted({lbl for lbl, _ in pairs}) or ["NONE"]
    return {
        "relevance": max(1, min(5, rel)),
        "groundedness": max(1, min(5, gnd)),
        "citation_accuracy": max(1, min(5, cit)),
        "critical_errors": errs,
        "critical_error_quotes": pairs,
        # Was [:300], which cut rationales mid-word and destroyed the audit trail:
        # a run listing several objections was stored with the list itself removed,
        # so every later reader reasoned about a vote whose grounds were missing.
        "short_rationale": str(data.get("short_rationale", "")).strip()[:_MAX_RATIONALE_CHARS],
    }


def _norm_ws(s: str) -> str:
    """Whitespace-fold + casefold. The single normalization used both to check a
    quote resolves in the candidate and to locate its span for vote grouping —
    one function, so the two can never disagree about what "the same text" is."""
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def _quote_is_in_candidate(quote: str, candidate: str) -> bool:
    """A critical-error vote must point at text the candidate actually wrote.

    Two of the six carried-over errors were founded on text that appears nowhere in
    the answer being judged — one run quoted figures that occur only in the *reference*
    answer, i.e. it graded the wrong document. Whitespace- and case-insensitive so a
    reflowed copy still resolves.

    Fails OPEN on an empty quote: stored rows from before the rubric change carry none,
    and re-aggregating them must stay byte-identical.
    """
    if not quote:
        return True
    return _norm_ws(quote) in _norm_ws(candidate)


def _accused_spans(quotes: list[str], cand_norm: str) -> list[tuple[int, int]]:
    """Normalized [start, end) interval of each locatable quote in the candidate.

    First occurrence when the quoted text repeats — deterministic, and a quote
    that repeats verbatim is the same accusation wherever it sits. A quote that
    does not resolve contributes no span (the vote itself was already validated
    by :func:`_quote_is_in_candidate`; an empty result here makes it a wildcard)."""
    spans = []
    for q in quotes:
        qn = _norm_ws(q)
        if not qn:
            continue
        i = cand_norm.find(qn)
        if i >= 0:
            spans.append((i, i + len(qn)))
    return spans


def _max_same_span_votes(per_run_spans: list[list[tuple[int, int]]]) -> int:
    """Highest number of runs accusing the SAME text, where "same" means their
    quoted spans overlap in the candidate.

    Label-only counting manufactured freeze1's sole gate blocker: on h07, run 1
    accused the FAQ-formula sentence and run 2 accused a citation three
    paragraphs away — neither span was accused twice, yet
    ``counts['CITATION_WRONG'] == 2`` read as a majority. A majority must be a
    majority ON A SPAN, or three runs each flagging a different weak sentence
    convict an answer no two of them agree about.

    Overlap, not string equality: two runs quoting different 5-25-word windows
    of the same defective sentence are the same accusation.

    A run with NO locatable span is a WILDCARD that supports every span group of
    its label: pre-quote-era per_run rows carry bare labels (and
    ``_quote_is_in_candidate`` fails open on them by contract), so all-wildcard
    voting reproduces label-only counting byte-identically on stored rows.
    """
    wildcards = sum(1 for spans in per_run_spans if not spans)
    intervals = [(s, e, idx)
                 for idx, spans in enumerate(per_run_spans) for s, e in spans]
    if not intervals:
        return wildcards
    intervals.sort()
    best = 0
    cur_end = -1
    cur_runs: set[int] = set()
    for s, e, idx in intervals:
        if not cur_runs or s >= cur_end:      # half-open: touching is not overlap
            best = max(best, len(cur_runs))
            cur_runs = {idx}
            cur_end = e
        else:
            cur_runs.add(idx)
            cur_end = max(cur_end, e)
    return max(best, len(cur_runs)) + wildcards


def _judge_once(
    question: str, evidence: str, expected: str, candidate: str,
    model: str = JUDGE_MODEL_FAST,
) -> dict | None:
    """One judge call. Returns parsed dict or None on failure (1 retry).

    Judges are verifier-style calls — we pass ``temperature=0.0`` so the same
    (question, evidence, candidate) yields the same verdict. Today the CLI
    ignores this argument (see ``claude_bridge`` docstring) but recording the
    intent makes the SDK port a no-op for callers."""
    user = JUDGE_USER.format(
        question=question, evidence=evidence, expected=expected, candidate=candidate,
    )
    for attempt in range(2):  # 1 retry on parse failure
        try:
            raw = _call_claude(model, JUDGE_SYSTEM, user, temperature=0.0)
        except ClaudeCLIError:
            return None
        parsed = _parse_judge_json(raw)
        if parsed is not None:
            return parsed
    return None


# ── B3: multi-run median + flip-rate ─────────────────────────────────


def _median_int(values: list[int]) -> int:
    if not values:
        return 0
    return int(round(statistics.median(values)))


def _flip_rate(values: list[int]) -> float:
    """Fraction of pairwise disagreements between consecutive runs.
    With N=3, the maximum is 2/2 = 1.0 (every consecutive pair disagrees)."""
    if len(values) < 2:
        return 0.0
    diffs = sum(1 for a, b in zip(values, values[1:]) if a != b)
    return diffs / (len(values) - 1)


def _judge_llm_aggregated(
    question: str, evidence: str, expected: str, candidate: str,
    n_runs: int = DEFAULT_JUDGE_RUNS,
) -> dict:
    """Run the judge n_runs times, aggregate per-axis. Escalate to strong model
    when median relevance lands at 3 (book Chapter 9 §9.1.3 tiered escalation)."""
    runs = []
    for _ in range(n_runs):
        r = _judge_once(question, evidence, expected, candidate, model=JUDGE_MODEL_FAST)
        if r is not None:
            runs.append(r)
    if not runs:
        return {
            "relevance": None, "groundedness": None, "citation_accuracy": None,
            "critical_errors": ["NONE"], "short_rationale": "(judge failed)",
            "flip_rate_relevance": None, "flip_rate_groundedness": None,
            "n_runs": 0, "escalated": False,
        }

    rels = [r["relevance"] for r in runs]
    gnds = [r["groundedness"] for r in runs]
    cits = [r["citation_accuracy"] for r in runs]

    median_rel = _median_int(rels)
    median_gnd = _median_int(gnds)
    median_cit = _median_int(cits)

    # Tiered escalation: borderline median (== 3) on relevance gets 1 strong run
    escalated = False
    if median_rel == 3:
        strong = _judge_once(question, evidence, expected, candidate, model=JUDGE_MODEL_STRONG)
        if strong is not None:
            escalated = True
            # Strong run is the deciding vote: replace median with strong if outside 3
            if strong["relevance"] != 3:
                median_rel = strong["relevance"]
            if strong["groundedness"] != median_gnd:
                median_gnd = _median_int(gnds + [strong["groundedness"]])
            if strong["citation_accuracy"] != median_cit:
                median_cit = _median_int(cits + [strong["citation_accuracy"]])

    # Aggregate critical_errors by MAJORITY across runs, not union.
    #
    # Union was inconsistent with the rest of the aggregation — scores use the
    # median, so a single dissenting run cannot move them, but a single dissenting
    # run could permanently brand an answer with a gate-blocking critical error.
    # With a measured relevance flip-rate of ~0.16 that is not a rare event, and
    # the false-positive count grows with --judge-runs by construction: the
    # baseline regeneration produced 10 blocking violations, 4 of which were
    # flagged by exactly 1 of 3 runs on answers judged EQUIVALENT at relevance
    # 4-5. An error worth blocking a release should be one the judges agree on.
    #
    # A vote is also discarded when the run cannot point at the text it accuses —
    # see _quote_is_in_candidate. Every one of the six carried-over errors sat at
    # exactly 2-of-3, never unanimous, so dropping one unfounded vote is decisive.
    #
    # Voting is SPAN-AWARE (see _max_same_span_votes): counting labels alone let
    # two runs accusing two disjoint spans read as a majority neither span earned
    # — freeze1's sole gate blocker (h07 CITATION_WRONG) was exactly that
    # artifact. A label survives only if some single span collects a majority.
    threshold = (len(runs) // 2) + 1 if len(runs) > 1 else 1
    cand_norm = _norm_ws(candidate)
    votes: dict[str, list[list[tuple[int, int]]]] = {}
    for r in runs:
        quotes = r.get("critical_error_quotes") or []
        for e in set(r["critical_errors"]):          # one vote per run per label
            if e == "NONE":
                continue
            qs = [q for lbl, q in quotes if lbl == e]
            if qs and not any(_quote_is_in_candidate(q, candidate) for q in qs):
                continue                              # accuses text the answer never contains
            votes.setdefault(e, []).append(_accused_spans(qs, cand_norm))
    errors_out = sorted(
        e for e, spans in votes.items() if _max_same_span_votes(spans) >= threshold
    ) or ["NONE"]

    rationale = runs[0]["short_rationale"]

    return {
        "relevance": median_rel,
        "groundedness": median_gnd,
        "citation_accuracy": median_cit,
        "critical_errors": errors_out,
        "short_rationale": rationale,
        "flip_rate_relevance": _flip_rate(rels),
        "flip_rate_groundedness": _flip_rate(gnds),
        "n_runs": len(runs),
        "escalated": escalated,
        "per_run": runs,
    }


# ── Rule-based judges (numeric / negative / page_lookup) ─────────────


_NUM_RE = re.compile(r"-?\d+(?:[.,]\d+)?")

# Reference-like number tokens that are NOT answer values: page/section/figure/
# table/chunk pointers and the like. These are stripped before number extraction
# so an answer such as "the COGS figures are on pages 30-32" no longer spuriously
# "matches" an expected value of 30.5 or 32.5 (finding F13).
_REF_TOKEN_RE = re.compile(
    r"\b(?:pages?|pp?\.?|sections?|figures?|figs?\.?|tables?|chunks?|steps?|"
    r"chapters?|paras?\.?|paragraphs?|lines?|rows?|cols?\.?|columns?|items?|"
    r"appendix|appendices|slides?|questions?|q)\s*"
    r"#?\s*\d+(?:\s*[-–—]\s*\d+)?",
    re.IGNORECASE,
)


def _extract_numbers(text: str, strip_references: bool = True) -> list[float]:
    text = text or ""
    if strip_references:
        text = _REF_TOKEN_RE.sub(" ", text)
    out = []
    for m in _NUM_RE.findall(text):
        clean = m.replace(",", "")
        try:
            out.append(float(clean))
        except ValueError:
            continue
    return out


def _percent_variants(ev: float) -> list[float]:
    """Accept a percentage written either as ``32.5`` or as its decimal form ``0.325``.

    h13 asks for a COGS percentage whose gold value is 32.5, but the workbook
    stores ``0.325`` with a separate "%" units column. An answer that faithfully
    quotes the cell scored relevance 1 with WRONG_EVIDENCE — an always-blocking
    gate rule for numeric questions — while a paraphrasing answer passed. That
    scores representation, not correctness.

    Only the ÷100 form is added, never ×100: the inverse would let ``72`` satisfy
    an expected ``7200`` (h15's monthly fixed costs), which is a real
    false-positive. The ÷100 direction is safe here because the spurious partner
    of a plausible answer value (e.g. 0.0079 for h14's $0.79) is not a number any
    answer to these questions would contain.
    """
    variants = [ev]
    if 0 < abs(ev) <= 100:
        variants.append(ev / 100.0)
    return variants


def _judge_numeric(actual: str, expected_numbers: list[float], tolerance: float = 0.05) -> dict:
    """Per-expected-number tolerance match, over answer numbers with page/section/
    table references stripped out first.

    ALL expected numbers matched → relevance 5; some → 3; none → 1.

    Critical-error labeling is failure-mode specific (finding F13): an answer that
    asserts *wrong* numbers is WRONG_EVIDENCE (an always-blocking rule for numeric
    questions — correct). An answer with *no* number at all is a FORMAT_FAIL /
    non-answer, NOT a HALLUCINATION — the old code mislabeled a correct
    refusal-style answer as HALLUCINATION, which is an always-blocking gate rule,
    so one flaky digit-free answer hard-failed CI under the wrong label.
    """
    if not expected_numbers:
        rel = 1
        no_numbers = True
    else:
        actual_nums = _extract_numbers(actual)
        no_numbers = not actual_nums
        if no_numbers:
            rel = 1
        else:
            matched = sum(
                1 for ev in expected_numbers
                if any(
                    abs(a - c) <= max(abs(c) * tolerance, 1e-9)
                    for c in _percent_variants(ev)
                    for a in actual_nums
                )
            )
            if matched == len(expected_numbers):
                rel = 5
            elif matched > 0:
                rel = 3
            else:
                rel = 1
    if rel >= 4:
        errors = ["NONE"]
    elif rel == 1:
        # No number produced → format/non-answer; wrong number(s) → wrong evidence.
        errors = ["FORMAT_FAIL"] if no_numbers else ["WRONG_EVIDENCE"]
    else:
        errors = ["NONE"]
    return {
        "relevance": rel, "groundedness": rel, "citation_accuracy": rel,
        "critical_errors": errors,
        "short_rationale": f"numeric coverage: {rel}/5"
                           + (" (no number in answer)" if no_numbers and expected_numbers else ""),
        "flip_rate_relevance": 0.0, "flip_rate_groundedness": 0.0,
        "n_runs": 0, "escalated": False, "per_run": [],
    }


_NEGATIVE_PHRASES = (
    "no.", "not mentioned", "doesn't mention", "does not mention",
    "no mention", "not in the materials", "not in the documents",
    "i don't see", "i do not see", "none of the", "no document",
    "no, ", "not covered", "not described", "not addressed",
    "outside the scope", "does not appear", "do not appear",
    "is not mentioned", "are not mentioned",
)


def _judge_negative(actual: str) -> dict:
    """For 'is X mentioned?' negative questions. Looks for explicit refusal phrasing."""
    a = (actual or "").strip().lower()
    hit = any(p in a for p in _NEGATIVE_PHRASES)
    if not hit and a.startswith("no") and len(a) >= 3 and a[2] in (" ", ",", ".", ":", ";", "-"):
        hit = True
    rel = 5 if hit else 1
    # F14: the old ``["OVER_REFUSAL", "HALLUCINATION"][1:1]`` sliced to [], so a
    # failed negative question — the system asserting content that isn't in the
    # corpus, i.e. the textbook hallucination — emitted NO critical error and was
    # invisible to the summary counter, the gate's critical-error rules, and the
    # oracle/calibration harnesses. A failed negative IS a hallucination.
    return {
        "relevance": rel, "groundedness": rel, "citation_accuracy": rel,
        "critical_errors": ["NONE"] if hit else ["HALLUCINATION"],
        "short_rationale": "negative refusal detected" if hit else "expected refusal but answer asserts content",
        "flip_rate_relevance": 0.0, "flip_rate_groundedness": 0.0,
        "n_runs": 0, "escalated": False, "per_run": [],
    }


_PAGE_ASSERTION_RE = re.compile(
    r"^\s*(?:pages?|pp?\.?|pg\.?)\s*([\d\s,\-–—]+?)\s*$", re.IGNORECASE
)


def _answer_pages(actual: str) -> set[int]:
    """Every page number an answer references, in any supported phrasing.

    Unions the pages from structured citations (``[source, pages 7-8]``) with
    bare prose mentions (``on p. 8``), so page recognition does not depend on
    which of the accepted citation shapes the model happened to use.
    """
    pages: set[int] = set()
    for c in parse_citations(actual or ""):
        pages.update(c.get("pages") or [])
    for grp in parse_page_only_mentions(actual or ""):
        pages.update(grp)
    return pages


# Word-separator runs, folded to a single space before the fallback substring
# test. Hyphen family + underscore + every flavour of space, including NBSP and
# the soft hyphen a PDF extractor can leave mid-word.
_WORD_SEPARATOR_RE = re.compile(
    r"[\s ­‐‑‒–—―−_-]+"
)


def _collapse_separators(s: str) -> str:
    """Fold every word-separator run to one space, so ``table-turn`` and
    ``table  turn`` compare equal to ``table turn``."""
    return _WORD_SEPARATOR_RE.sub(" ", s or "").strip()


def _phrase_satisfied(phrase: str, actual_lower: str, answer_pages: set[int]) -> bool:
    """Is one ``must_contain`` entry satisfied by the answer?

    Entries that are *page assertions* (``"page 8"``, ``"pages 2"``) are matched
    semantically against the pages the answer actually cites, because the
    literal-substring test made them a **citation-format** test rather than a
    content test: the format this repo pins in ``QA_SYSTEM`` renders
    ``[5 KPIs …, pages 7-8]``, which does not contain the substring "page 8".
    That differentially penalized answers by prose style — fatal for an
    architecture comparison, and on h06 (holdout) it was the only phrase, so a
    correct answer fell to relevance 1 with a gate-blocking WRONG_EVIDENCE.

    Ordinary phrases are case-insensitive substrings, then retried with word
    separators folded. The second pass is the same defect one level down: a
    literal test on ``"table turn"`` is an **orthography** test, not a content
    test. h01's two generation seeds wrote "table turn time" and "table-turn
    speed" — the same claim, one hyphen apart — and scored 3 and 1, the latter
    with a gate-blocking WRONG_EVIDENCE, because ``must_contain`` is
    all-or-nothing when every phrase misses. Replayed over all 19 stored result
    files (193 phrase-checks), folding changes exactly that one cell and
    regresses none.

    Both relaxations run only after the plain test fails, so this is strictly
    more permissive than the old behavior: it can turn a spurious failure into a
    pass, never the reverse.
    """
    m = _PAGE_ASSERTION_RE.match(phrase or "")
    if m:
        wanted = _expand_pages(m.group(1))
        if wanted and all(p in answer_pages for p in wanted):
            return True
    p = (phrase or "").lower()
    if p in actual_lower:
        return True
    return _collapse_separators(p) in _collapse_separators(actual_lower)


# Abstention detector for the page_lookup rule branches. Anchored on the CONTEXT
# being the thing that lacks the fact — "the provided context does not define
# KPI #5", "not in the supplied context" — and NEVER on first-person inability:
# norerank h04's answer says "I can't pinpoint a single page number" while
# confidently presenting the wrong worked example, and it must stay
# WRONG_EVIDENCE. A hedge about page granularity is not an abstention.
# Designed on TUNING answers only (freeze1/verify1/verify2 h01, norerank h04)
# plus planted probes; holdout output was never read.
_ABSTENTION_RE = re.compile(
    # form A: <context-noun> ... <negation> <lack-verb>
    r"(?:context|excerpts?|materials?|documents?|chunks?)\b"
    r"[^.!?\n]{0,80}?"
    r"(?:do(?:es)?\s+not|don['’]t|doesn['’]t|didn['’]t|did\s+not|"
    r"cannot|can['’]t|never|fails?\s+to)\s+"
    r"(?:actually\s+|explicitly\s+|directly\s+)?"
    r"(?:define|contain|include|specify|state|mention|provide|identify|name|"
    r"give|list|show|cover|address|answer|appear|say|tell)"
    r"|"
    # form B: not in/included in/... the (provided) context
    r"\bnot\s+(?:in|included\s+in|present\s+in|provided\s+in|available\s+in|"
    r"found\s+in|shown\s+in|contained\s+in|part\s+of)\s+"
    r"(?:the\s+|this\s+|that\s+|my\s+)?"
    r"(?:provided\s+|supplied\s+|given\s+|shown\s+|available\s+|retrieved\s+)?"
    r"(?:context|excerpts?|materials?|documents?|chunks?)\b",
    re.IGNORECASE,
)


def _is_abstention(actual: str) -> bool:
    """Does the answer say the CONTEXT lacks the asked-for fact? One hit anywhere
    suffices — an honest abstention states its ground at least once."""
    return bool(_ABSTENTION_RE.search(actual or ""))


def _judge_page_lookup(
    actual: str, must_contain: list[str], expected: str, question: str, evidence: str,
    n_runs: int = DEFAULT_JUDGE_RUNS,
) -> dict:
    """Substring + LLM hybrid. All must_contain phrases present → at least 3, then
    let LLM judge resolve to 4 or 5 based on full answer correctness.

    Page-number phrases are matched against the answer's parsed citations rather
    than as raw substrings — see :func:`_phrase_satisfied`.

    The rule branches were wrong in BOTH directions until Aug 2026, measured by
    running planted answers through the real code:

    * All-miss branded every answer WRONG_EVIDENCE — but ``must_contain`` is a
      content-PRESENCE proxy, so all-miss is the union of {asserted something
      wrong} and {asserted nothing}: an honest abstention after a retrieval miss
      contains none of the required phrases BY CONSTRUCTION and scored
      byte-identically to a fabrication. That is F13 (`_judge_numeric`, which
      fixed exactly this) unfixed one judge over. The floor for an abstention is
      FORMAT_FAIL — still relevance 1, still a named non-answer, never NONE (so
      h01's real, reproducible retrieval miss stays visible) — but not an
      accusation the answer never earned.
    * The partial branch could not fire at all, so the single defect a
      page_lookup question exists to catch — right entity, fabricated page —
      scored 3/3/3 with NO error. Now: a missed ``page N`` assertion, on an
      answer that does cite pages and does not abstain, is a wrong-page claim →
      CITATION_WRONG at 2/2/2 (gate-blocking on must-cite questions).

    Chunk-grain citations cannot trip the new branch: satisfaction is
    subset-based over the expanded union of cited ranges, so ``[src, pages 1-3]``
    against gold page 2 satisfies before any accusation is considered (h06's
    ceiling stays a ceiling, not an error). Residual, documented: a fabrication
    that also plants abstention wording escapes with the softer label — axes
    still floor at 1-2 and the verdict is still DIFFERENT, so nothing passes."""
    a = (actual or "").lower()
    answer_pages = _answer_pages(actual)
    missing = [p for p in must_contain if not _phrase_satisfied(p, a, answer_pages)]
    if missing and len(missing) == len(must_contain):
        abstained = _is_abstention(actual)
        return {
            "relevance": 1, "groundedness": 1, "citation_accuracy": 1,
            "critical_errors": ["FORMAT_FAIL"] if abstained else ["WRONG_EVIDENCE"],
            "short_rationale": (
                f"none of {must_contain} present"
                + ("; answer abstains (context-lack stated) — a retrieval miss, "
                   "not a wrong assertion" if abstained else "")
            ),
            "flip_rate_relevance": 0.0, "flip_rate_groundedness": 0.0,
            "n_runs": 0, "escalated": False, "per_run": [],
        }
    if missing:
        # Right-entity / wrong-page detector. Only page assertions gain teeth:
        # a missed ordinary phrase stays an incompleteness (3), not a defect.
        wanted_missed: set[int] = set()
        for p in missing:
            m = _PAGE_ASSERTION_RE.match(p or "")
            if m:
                wanted_missed.update(_expand_pages(m.group(1)))
        if wanted_missed and answer_pages and not _is_abstention(actual):
            return {
                "relevance": 2, "groundedness": 2, "citation_accuracy": 2,
                "critical_errors": ["CITATION_WRONG"],
                "short_rationale": (
                    f"cites pages {sorted(answer_pages)} but never the gold "
                    f"page(s) {sorted(wanted_missed)} — a wrong-page claim, "
                    f"not an abstention"),
                "flip_rate_relevance": 0.0, "flip_rate_groundedness": 0.0,
                "n_runs": 0, "escalated": False, "per_run": [],
            }
        return {
            "relevance": 3, "groundedness": 3, "citation_accuracy": 3,
            "critical_errors": ["NONE"],
            "short_rationale": f"missing {missing}",
            "flip_rate_relevance": 0.0, "flip_rate_groundedness": 0.0,
            "n_runs": 0, "escalated": False, "per_run": [],
        }
    # All present: defer to LLM judge for 4 vs 5 distinction
    return _judge_llm_aggregated(question, evidence, expected, actual, n_runs=n_runs)


# ── Unified dispatch ─────────────────────────────────────────────────


def _judge(record: dict, actual: str, evidence: str,
           n_runs: int = DEFAULT_JUDGE_RUNS) -> dict:
    """Route to the judge for this question type.

    ``n_runs`` is threaded all the way to ``_judge_llm_aggregated``. It previously
    was not: ``--judge-runs`` was accepted, echoed in the banner and the results
    envelope, and then dropped — every run used DEFAULT_JUDGE_RUNS regardless.
    CLAUDE.md advertised ``--judge-runs 5`` as a way to tighten the median, so any
    flip-rate or median-stability conclusion drawn from it compared identical
    3-run configurations. Default is unchanged, so calibrate.py and oracle.py keep
    working untouched."""
    qtype = record["question_type"]
    if qtype == "numeric":
        return _judge_numeric(actual, record["expected_numbers"])
    if qtype == "negative":
        return _judge_negative(actual)
    if qtype == "page_lookup":
        return _judge_page_lookup(
            actual, record["must_contain"], record["expected_answer"],
            record["question"], evidence, n_runs=n_runs,
        )
    # qa, synthesis: full LLM judge
    return _judge_llm_aggregated(
        record["question"], evidence, record["expected_answer"], actual,
        n_runs=n_runs,
    )


# ── Judge code hash ──────────────────────────────────────────────────
#
# `judge_prompt_hash` = prompt_hash(JUDGE_SYSTEM, JUDGE_USER) covers the LLM
# rubric STRINGS and nothing else, so every judge decision made in Python is
# invisible to eval/gate.py's comparability warning. Twice now that blindness has
# hidden a real scoring change on byte-identical answers:
#
#   * critical errors moved from unioned to MAJORITY-voted across judge runs
#     (`_judge_llm_aggregated`), taking gate-blocking errors 6 -> 0;
#   * `_phrase_satisfied` learned to fold word separators, flipping h01 from
#     DIFFERENT 1/1/1 + WRONG_EVIDENCE to PARTIAL 3/3/3.
#
# Both left judge_prompt_hash at ba29d7420a62. The registry below is therefore
# the WHOLE judge decision surface, not just the rule-based judges: 15 of the 25
# hard questions route through rule code (6 page_lookup + 5 numeric + 4 negative)
# and page_lookup is a HYBRID — the rule decides the 1-vs-3 outcomes and the LLM
# only resolves 4-vs-5 — so on those six questions both hashes are load-bearing
# at once.
#
# `_expand_pages` is deliberately included even though it lives in citations.py:
# `_phrase_satisfied` resolves every page assertion through it, so its range
# parsing is judge behaviour regardless of which module hosts it.
_JUDGE_CODE_SYMBOLS = (
    # Dispatch + rule-based judges
    ("_judge", _judge),
    ("_judge_page_lookup", _judge_page_lookup),
    ("_judge_numeric", _judge_numeric),
    ("_judge_negative", _judge_negative),
    # page_lookup helpers
    ("_phrase_satisfied", _phrase_satisfied),
    ("_collapse_separators", _collapse_separators),
    ("_answer_pages", _answer_pages),
    ("_expand_pages", _expand_pages),          # cross-module: citations.py
    ("_PAGE_ASSERTION_RE", _PAGE_ASSERTION_RE),
    ("_WORD_SEPARATOR_RE", _WORD_SEPARATOR_RE),
    ("_ABSTENTION_RE", _ABSTENTION_RE),
    ("_is_abstention", _is_abstention),
    # numeric helpers
    ("_extract_numbers", _extract_numbers),
    ("_percent_variants", _percent_variants),
    ("_REF_TOKEN_RE", _REF_TOKEN_RE),
    ("_NUM_RE", _NUM_RE),
    # negative helper
    ("_NEGATIVE_PHRASES", _NEGATIVE_PHRASES),
    # LLM judge plumbing: parsing, vote filtering, aggregation, escalation
    ("_judge_once", _judge_once),
    ("_judge_llm_aggregated", _judge_llm_aggregated),
    ("_parse_judge_json", _parse_judge_json),
    ("_quote_is_in_candidate", _quote_is_in_candidate),
    ("_norm_ws", _norm_ws),
    ("_accused_spans", _accused_spans),
    ("_max_same_span_votes", _max_same_span_votes),
    ("_flip_rate", _flip_rate),
    ("_VALID_ERRORS", _VALID_ERRORS),
    # verdict mapping — turns a relevance score into the EQUIVALENT/PARTIAL/
    # DIFFERENT label every headline count is computed from
    ("_verdict_from_relevance", _verdict_from_relevance),
)


def judge_code_hash() -> str:
    """Comparability hash over the judge decision surface. See the note above."""
    return code_hash(_JUDGE_CODE_SYMBOLS)


# ── Question normalization ───────────────────────────────────────────


def _nfc(s):
    return unicodedata.normalize("NFC", s) if isinstance(s, str) else s


def _parse_pages(raw):
    if isinstance(raw, list):
        return [int(x) for x in raw]
    if not isinstance(raw, str):
        return []
    raw = raw.strip()
    try:
        if raw.startswith("["):
            return [int(x.strip()) for x in raw.strip("[]").split(",") if x.strip()]
        return [int(raw)]
    except ValueError:
        return []


def _normalize_question(q: dict) -> dict:
    """Coerce both legacy and current question schemas into the harness's
    internal record. Preserves the Phase-D1 ``holdout`` flag so the runner
    can filter by subset before iterating."""
    out = {
        "id": q["id"],
        "question": q["question"],
        "expected_answer": q.get("expected_answer", ""),
        "question_type": q.get("question_type", "qa"),
        "must_cite_sources": [],
        "must_contain": q.get("must_contain", []),
        "expected_numbers": q.get("expected_numbers", []),
        "holdout": bool(q.get("holdout", False)),
    }
    if "must_cite_sources" in q and q["must_cite_sources"]:
        out["must_cite_sources"] = q["must_cite_sources"]
    elif q.get("must_cite_source"):
        out["must_cite_sources"] = [{"source": q["must_cite_source"], "pages": None}]
    return out


# ── Recall + ranking metrics ─────────────────────────────────────────


def _compute_recall(retrieved: list[dict], must_cite_sources: list[dict]) -> dict:
    """Source-level + page-level recall."""
    if not must_cite_sources:
        return {
            "applicable": False,
            "source_full": None, "pages_full": None, "partial": None,
            "per_source": [],
        }
    retrieved_idx = []
    for c in retrieved:
        retrieved_idx.append({
            "source": _nfc(c.get("source", "")),
            "pages": _parse_pages(c.get("pages")),
        })
    per_source = []
    for entry in must_cite_sources:
        wanted_src = _nfc(entry["source"])
        wanted_pages = entry.get("pages") or []
        src_hit = any(r["source"] == wanted_src for r in retrieved_idx)
        if wanted_pages:
            page_hit = any(
                r["source"] == wanted_src and any(p in wanted_pages for p in r["pages"])
                for r in retrieved_idx
            )
        else:
            page_hit = src_hit
        per_source.append({
            "source": entry["source"],
            "wanted_pages": wanted_pages,
            "source_hit": src_hit,
            "page_hit": page_hit,
        })
    return {
        "applicable": True,
        "source_full": all(p["source_hit"] for p in per_source),
        "pages_full": all(p["page_hit"] for p in per_source),
        "partial": sum(p["source_hit"] for p in per_source) / len(per_source),
        "per_source": per_source,
    }


# ── C1: MRR + nDCG ───────────────────────────────────────────────────


def _is_relevant_chunk(chunk: dict, must_cite_sources: list[dict]) -> bool:
    """A retrieved chunk counts as relevant if (a) its source matches a wanted
    source AND (b) either no pages were specified, or its pages overlap the
    wanted pages."""
    src = _nfc(chunk.get("source", ""))
    pages = _parse_pages(chunk.get("pages"))
    for entry in must_cite_sources:
        if _nfc(entry["source"]) != src:
            continue
        wanted_pages = entry.get("pages") or []
        if not wanted_pages:
            return True
        if any(p in wanted_pages for p in pages):
            return True
    return False


def _mrr_at_k(retrieved: list[dict], must_cite_sources: list[dict], k: int) -> float | None:
    """Reciprocal rank of the FIRST relevant chunk in top-k. None if no gold."""
    if not must_cite_sources:
        return None
    for rank, c in enumerate(retrieved[:k], start=1):
        if _is_relevant_chunk(c, must_cite_sources):
            return 1.0 / rank
    return 0.0


def _ndcg_at_k(retrieved: list[dict], must_cite_sources: list[dict], k: int) -> float | None:
    """nDCG@k with binary relevance per chunk. None if no gold."""
    if not must_cite_sources:
        return None
    rels = [1 if _is_relevant_chunk(c, must_cite_sources) else 0 for c in retrieved[:k]]
    dcg = sum(r / math.log2(i + 2) for i, r in enumerate(rels))
    # Ideal: as many 1s at top as there are total relevant items, capped at k
    n_rel = sum(rels)
    ideal = [1] * n_rel + [0] * (k - n_rel)
    idcg = sum(r / math.log2(i + 2) for i, r in enumerate(ideal)) or 1.0
    return dcg / idcg


# ── Main loop ────────────────────────────────────────────────────────


_GOLD_EVIDENCE_CACHE: dict[str, str] = {}


def _gold_evidence(q: dict) -> str:
    """The question's gold passages, rendered exactly as any arm's context is.

    Identical for every arm, so ``groundedness`` becomes a comparable
    *reference-grounding* score instead of a per-arm faithfulness score. Note
    those are different constructs: gold is a superset of what arm A retrieved,
    so this mode cannot detect arm A confabulating beyond a thin-but-correct
    context. The report must name the axis accordingly.

    Empty for negative questions (no gold passage by construction) — harmless,
    because negatives never reach the LLM judge.
    """
    qid = q["id"]
    if qid not in _GOLD_EVIDENCE_CACHE:
        from pipeline import _format_context
        from eval.gold import gold_chunks_for_question, GoldSourceMissing
        try:
            chunks = gold_chunks_for_question(q["must_cite_sources"], project=EVAL_PROJECT)
        except GoldSourceMissing as e:
            # Loud: an unresolvable gold source silently degrades the reference
            # evidence to nothing, which is exactly the bug eval/gold.py exists
            # to prevent.
            print(f"     GOLD SOURCE MISSING for {qid}: {e.source!r}")
            chunks = []
        _GOLD_EVIDENCE_CACHE[qid] = _format_context(chunks) if chunks else ""
    return _GOLD_EVIDENCE_CACHE[qid]


_CORPUS_EVIDENCE_CACHE: str | None = None


def _corpus_evidence() -> str:
    """The entire corpus as the judge's evidence block.

    Why this mode exists — the pilot proved the other two are both biased:

    * ``own`` hands an arm with no shown context (agentic file search) an EMPTY
      evidence block. The judge correctly reports that nothing can be verified
      and returns groundedness 1 + HALLUCINATION. Pure harness artifact.
    * ``gold`` penalises any arm that reads *beyond* the label. Gold page sets in
      this repo are chunk-shaped — they record where arm A's retriever found the
      answer, not everywhere the fact appears. Measured on pilot question h07:
      arm C cited Briefing Doc pages 1 and 7, the judge called that invention,
      and the source text shows page 1 really does carry a second break-even
      formula ("Fixed Costs / (Selling Price per Unit - Cost per Unit)") and the
      doubling-wholesale-cost line, while page 7 defines Gross Margin. The answer
      was right; the label was incomplete. Arms B and C see the whole corpus, so
      they hit this systematically — it would have biased the entire comparison
      toward arm A.

    The corpus is the actual ground truth, it is byte-identical for every arm,
    and it depends on no label. Cost is real (~294K chars per LLM-judged call),
    which is why it is opt-in rather than the default.
    """
    global _CORPUS_EVIDENCE_CACHE
    if _CORPUS_EVIDENCE_CACHE is None:
        from eval.arms import build_full_corpus_context
        ctx, _, _ = build_full_corpus_context(EVAL_PROJECT)
        _CORPUS_EVIDENCE_CACHE = ctx
    return _CORPUS_EVIDENCE_CACHE


_ALL_CHUNKS_CACHE: list[dict] | None = None


def _all_corpus_chunks() -> list[dict]:
    """Every chunk in the eval project, loaded once per process.

    The validation universe for arms that have no retrieved set of their own.
    Note this makes citation precision mean "cites a real (source, page) that
    exists in the corpus" rather than "faithful to the shown context" — the two
    are different constructs and the ablation report must not blend them.
    """
    global _ALL_CHUNKS_CACHE
    if _ALL_CHUNKS_CACHE is None:
        from vectorstore import get_all_chunks
        _ALL_CHUNKS_CACHE = get_all_chunks(project=EVAL_PROJECT)
    return _ALL_CHUNKS_CACHE


_CORPUS_IDF_CACHE: dict | None = None


def _corpus_idf() -> dict:
    """IDF table for quote verification — ALWAYS corpus-wide, never the retrieved 10.

    Built from the same universe for every arm, so "is this token rare" means the
    same thing in arm A's score as in arm C's. Deriving it per-arm would make the
    quote verifier stricter for whichever arm happened to retrieve less.
    """
    global _CORPUS_IDF_CACHE
    if _CORPUS_IDF_CACHE is None:
        from citation_support import build_idf
        _CORPUS_IDF_CACHE = build_idf(_all_corpus_chunks())
    return _CORPUS_IDF_CACHE


def results_stem(hard: bool, arm: str, judge_evidence: str,
                 only: str | None, out_suffix: str = "") -> str:
    """Filename stem for a run's results. Every clause here exists because two
    runs silently landed on one file at some point.

    - Arm A keeps the historical name so ``eval/gate.py``'s default ``--current``
      path and the slow smoke test keep working untouched; other arms get their
      own, or three arms in sequence each overwrite the previous one.
    - ``--only`` forces ``_partial``: a subset run is not a full eval and must
      never land where the gate would read a 3-question pilot as a 25-question run.
    - ``out_suffix`` separates repeat samples of the *same* questions (a second
      generation seed), which every other clause would map to one filename.
    """
    stem = "results_hard" if hard else "results"
    if (arm or "A").upper() != "A":
        stem = f"{stem}_{arm.upper()}"
    if judge_evidence != "own":
        stem = f"{stem}_{judge_evidence}"
    if only:
        stem = f"{stem}_partial"
    if out_suffix:
        # Caller-supplied and lands in a path — keep it to characters that cannot
        # traverse out of eval/ or collide with the extension.
        safe = "".join(c if (c.isalnum() or c in "-_") else "_" for c in out_suffix)
        safe = safe.strip("_")[:32]
        if safe:
            stem = f"{stem}_{safe}"
    return stem


def run_eval(
    hard: bool = False,
    judge_runs: int = DEFAULT_JUDGE_RUNS,
    run_id: str | None = None,
    holdout: str = "all",
    arm: str = "A",
    cache_dir: str | Path | None = None,
    use_cache: bool = True,
    resume: bool = False,
    only: str | None = None,
    judge_evidence: str = "own",
    mirror_dir: str | None = None,
    agentic_timeout: int = 1800,
    agentic_output_format: str = "json",
    max_budget_usd: float | None = None,
    out_suffix: str = "",
    use_rerank: bool = True,
    citation_support: bool = CITATION_SUPPORT_ENABLED,
    support_runs: int = CITATION_SUPPORT_RUNS,
    support_cache_dir: str | None = None,
):
    fname = "questions_hard.json" if hard else "questions.json"
    out_stem = results_stem(hard, arm, judge_evidence, only, out_suffix)
    questions_path = Path(__file__).parent / fname
    questions = json.loads(questions_path.read_text(encoding="utf-8"))

    # ── D1: holdout split ──────────────────────────────────────────
    # ``holdout`` selects which subset of questions to run. The split is
    # encoded inline in questions_hard.json via the ``holdout: true`` flag.
    # Discipline rule (also in CLAUDE.md): never tune retrieval / prompts /
    # judge prompts based on the holdout subset. Iterate on tuning, freeze,
    # then run holdout once before quoting numbers.
    if holdout == "tuning":
        questions = [q for q in questions if not q.get("holdout", False)]
    elif holdout == "holdout":
        questions = [q for q in questions if q.get("holdout", False)]
    # else "all": leave the list alone

    # ``--only h04,h07`` — re-run specific questions without a full pass.
    if only:
        wanted = {s.strip() for s in only.split(",") if s.strip()}
        unknown = wanted - {q.get("id") for q in questions}
        if unknown:
            print(f"--only names unknown question ids: {sorted(unknown)}")
            sys.exit(1)
        questions = [q for q in questions if q.get("id") in wanted]

    arm = (arm or "A").upper()
    if run_id is None:
        run_id = f"eval_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    # Nested per arm so three arms of one run_id don't clobber each other's traces.
    trace_subdir = run_id if arm == "A" else f"{run_id}/{arm}"

    try:
        producer = make_producer(
            arm, project=EVAL_PROJECT, top_k=TOP_K,
            mirror_dir=mirror_dir, agentic_timeout=agentic_timeout,
            agentic_output_format=agentic_output_format,
            max_budget_usd=max_budget_usd, use_rerank=use_rerank,
        )
    except (ValueError, AgenticSandboxError) as e:
        print(f"{e}")
        sys.exit(1)
    cache = AnswerCache(
        Path(cache_dir) if cache_dir else ROOT / "data" / "answer_cache",
        enabled=use_cache,
    )
    checkpoint = Checkpoint(ROOT / "eval" / "partial" / f"{run_id}_{arm}.jsonl")

    # Cache prompt hash once for all traces this run
    qa_prompt_hash = prompt_hash(QA_SYSTEM, QA_USER)
    judge_prompt_hash = prompt_hash(JUDGE_SYSTEM, JUDGE_USER)
    jc_hash = judge_code_hash()

    _question_order = {q.get("id"): i for i, q in enumerate(questions)}
    done = checkpoint.load() if resume else {}
    results = [done[q["id"]] for q in questions if q.get("id") in done]
    if done:
        print(f"Resuming: {len(results)} question(s) already complete in {checkpoint.path.name}")
        # A resumed run stamps ONE judge_code_hash onto the envelope, but the
        # inherited records were scored by whatever judge code was loaded when
        # they were written. Editing a judge between the crash and the resume
        # therefore produces a file whose envelope quietly overclaims. Warn
        # rather than discard: re-judging costs plan quota, and that call is the
        # operator's. Records written before this field existed carry None and
        # are counted separately — unknown is not the same as matching.
        stale = [r.get("id") for r in results
                 if r.get("judge_code_hash") not in (jc_hash, None)]
        unstamped = [r.get("id") for r in results if r.get("judge_code_hash") is None]
        if stale:
            print(f"  WARN — {len(stale)} inherited record(s) were judged under DIFFERENT "
                  f"judge code than this run ({', '.join(stale[:6])}"
                  f"{'…' if len(stale) > 6 else ''}); the envelope's judge_code_hash "
                  f"{jc_hash} does not describe them. Re-run without --resume to rescore.")
        if unstamped:
            print(f"  WARN — {len(unstamped)} inherited record(s) predate judge_code_hash; "
                  f"cannot verify they were scored under this run's judge code.")
    questions = [q for q in questions if q.get("id") not in done]

    print(f"Running {'HARD' if hard else 'easy'} eval: {len(questions)} questions "
          f"(subset={holdout}), arm={arm} ({producer.name}), top_k={TOP_K}, "
          f"project={EVAL_PROJECT}, judge_runs={judge_runs}\n"
          f"Trace subdir: {trace_subdir}\n")
    t_start = time.time()

    for i, raw in enumerate(questions, 1):
        q = _normalize_question(raw)
        qid = q["id"]
        question = q["question"]
        qtype = q["question_type"]

        print(f"[{i:>2}/{len(questions)}] {qid} ({qtype}): {question[:60]}")

        # 1+2. Retrieval and generation — the ONE arm-dependent step. Everything
        # below this block is arm-agnostic and must stay that way.
        prod = cache.get_or_produce(
            producer, qid, question, qtype, CLAUDE_MODEL_QUALITY, qa_prompt_hash,
        )

        if prod.error:
            print(f"     ERROR: {prod.error}")
            err_record = {
                "id": qid, "question": question, "question_type": qtype,
                "holdout": q["holdout"],          # present on every record shape, so
                                                  # subset-grouping code can't KeyError
                "recall": {"applicable": False, "error": prod.error},
                "verdict": "ERROR", "actual_answer": "",
                "expected_answer": q["expected_answer"],
                "must_cite_sources": q["must_cite_sources"],
                "retrieved": [],
                "judge": {"relevance": None, "groundedness": None,
                          "citation_accuracy": None, "critical_errors": ["NONE"]},
                "mrr_at_10": None, "ndcg_at_10": None,
                "citation_validation": None,
                "arm": arm,
            }
            results.append(err_record)
            if not prod.fatal:
                # Non-fatal errors are a result. A fatal one is an infrastructure
                # outage, so it is deliberately NOT checkpointed — --resume must
                # retry that question rather than inherit the failure.
                checkpoint.append(err_record)
            if prod.fatal:
                # Quota / auth outage: stop instead of filling the remaining
                # questions with scored failures. A short run is recoverable; a
                # silently poisoned one is not.
                n_saved = len(checkpoint.load())
                print(
                    f"\nABORTING: {prod.error}\n"
                    f"  {n_saved} completed question(s) saved to {checkpoint.path}\n"
                    f"  {qid} was NOT saved and will be retried on resume.\n"
                    f"  Resume with: python eval/run.py"
                    f"{' --hard' if hard else ''} --arm {arm} --run-id {run_id} --resume\n"
                )
                sys.exit(2)
            continue

        chunks = prod.context_chunks
        evidence = prod.evidence_text
        retrieved_records = [
            {"source": c.get("source", "?"), "pages": c.get("pages")}
            for c in chunks
        ]

        # Recall / MRR / nDCG are RANKING metrics. A producer that does not rank
        # (whole-corpus, agentic file search) must not report them: feeding it the
        # whole corpus would yield a meaningless but authoritative-looking
        # "100% retrieval recall".
        if prod.retrieval_applicable:
            recall = _compute_recall(chunks, q["must_cite_sources"])
            mrr = _mrr_at_k(chunks, q["must_cite_sources"], k=TOP_K)
            ndcg = _ndcg_at_k(chunks, q["must_cite_sources"], k=TOP_K)
        else:
            recall = {"applicable": False, "reason": f"{producer.name} does not rank"}
            mrr = ndcg = None

        actual = prod.answer

        # 3. Citation validation (A3)
        # An arm with no chunk set of its own (agentic file search) must be
        # validated against the whole corpus, not against an empty list — the
        # latter would score every citation invalid for a structural reason and
        # report 0.0 precision for an arm that cited perfectly.
        # One variable for both checks, so a future edit cannot make the support
        # scorer and the existing validator diverge on arm C's universe.
        cit_universe = (_all_corpus_chunks() if prod.citation_scope == "corpus_only"
                        else chunks)
        cit_result = parse_and_validate(actual, cit_universe)

        claim_support = None
        if citation_support:
            from citation_support import llm_adjudicator, score_citation_support
            claim_support = score_citation_support(
                actual, cit_universe,
                scope=("corpus_only" if prod.citation_scope == "corpus_only" else "own"),
                runs=support_runs,
                adjudicator=llm_adjudicator(),
                idf=_corpus_idf(),
                cache_dir=support_cache_dir or CITATION_SUPPORT_CACHE_DIR,
            )

        # 4. Judge (B1+B2+B3)
        # Judge evidence selection.
        #   own  — the arm's own context. Faithfulness ("did it invent anything
        #          beyond what it saw"). Reproduces the pre-ablation semantics, so
        #          an `--arm A --judge-evidence own` run IS the baseline.
        #   gold — the question's gold passages, byte-identical across arms. The
        #          only mode in which the three arms are comparable.
        # Without this, an arm with no shown context (agentic file search) hands
        # the evidence-only judge an EMPTY block; the judge then correctly reports
        # that nothing can be verified and returns groundedness=1 with
        # HALLUCINATION. Measured in the pilot: arm C scored relevance 4-5 and
        # 2/3 EQUIVALENT while its groundedness collapsed to 1 purely because
        # evidence_text was "". That is a property of the harness, not the arm.
        if judge_evidence == "gold":
            judge_ev = _gold_evidence(q)
        elif judge_evidence == "corpus":
            judge_ev = _corpus_evidence()
        else:
            judge_ev = evidence
        judge_out = _judge(q, actual, judge_ev, n_runs=judge_runs)
        verdict = _verdict_from_relevance(judge_out["relevance"])

        # Reporting line
        if recall["applicable"]:
            src_s = "✓" if recall["source_full"] else "✗"
            pg_s = "✓" if recall["pages_full"] else "✗"
            mrr_s = f"{mrr:.2f}" if mrr is not None else "—"
            ndcg_s = f"{ndcg:.2f}" if ndcg is not None else "—"
        else:
            src_s = pg_s = "—"
            mrr_s = ndcg_s = "—"
        v_icon = {"EQUIVALENT": "✓", "PARTIAL": "~", "DIFFERENT": "✗", "ERROR": "!"}[verdict]
        rel = judge_out.get("relevance")
        gnd = judge_out.get("groundedness")
        cit = judge_out.get("citation_accuracy")
        rel_s = str(rel) if rel is not None else "—"
        gnd_s = str(gnd) if gnd is not None else "—"
        cit_s = str(cit) if cit is not None else "—"
        cite_acc = cit_result["validation"]["page_accuracy"]
        cite_s = f"{cite_acc:.2f}" if cite_acc is not None else "—"
        print(
            f"          recall src/pg: {src_s}/{pg_s}  MRR: {mrr_s}  nDCG: {ndcg_s}  "
            f"cite: {cite_s}  rel/gnd/cit: {rel_s}/{gnd_s}/{cit_s}  {v_icon} {verdict}"
        )

        # Persist trace (A1)
        trace = RagTrace(
            query_id=qid,
            query_text=question,
            retrieved_chunks=make_retrieved_records(chunks),
            reranked_chunks=[c.get("id") for c in chunks if c.get("id")],
            hyde_used=False,  # hybrid_search decides internally; reflect more precisely later
            answer=actual,
            parsed_citations=cit_result["parsed"],
            citation_validation=cit_result["validation"],
            versions={
                "model": CLAUDE_MODEL_QUALITY,
                "prompt_hash": qa_prompt_hash,
                "judge_prompt_hash": judge_prompt_hash,
                "judge_code_hash": jc_hash,
                "embedding_model": EMBEDDING_MODEL,
                "chunker_version": CHUNKER_VERSION,
                "reranker": RERANKER_MODEL,
                "arm": arm,
                "arm_name": producer.name,
                "arm_config_hash": producer.config_hash(),
            },
            telemetry={
                "judge_runs": judge_out.get("n_runs", 0),
                "judge_escalated": judge_out.get("escalated", False),
                **prod.telemetry,
            },
        )
        try:
            persist_trace(trace, subdir=trace_subdir)
        except Exception as e:
            print(f"     trace persist failed: {e}")

        record = {
            "id": qid,
            "question": question,
            "question_type": qtype,
            "holdout": q["holdout"],
            "must_cite_sources": q["must_cite_sources"],
            "retrieved": retrieved_records,
            "recall": recall,
            "mrr_at_10": mrr,
            "ndcg_at_10": ndcg,
            "verdict": verdict,
            "judge": judge_out,
            "citation_validation": cit_result["validation"],
            "citation_claim_support": claim_support,
            "actual_answer": actual,
            "expected_answer": q["expected_answer"],
            "arm": arm,
            # Stamped per record, not just per envelope, so --resume can tell
            # which inherited rows were scored by this run's judge code.
            "judge_code_hash": jc_hash,
            "telemetry": prod.telemetry,
        }
        results.append(record)
        # Flush per question: a session limit at question 20 used to lose all 20.
        checkpoint.append(record)

    elapsed = time.time() - t_start

    # Resumed records are prepended, so restore the question-file ordering before
    # aggregating and reporting.
    results.sort(key=lambda r: _question_order.get(r.get("id"), 1 << 30))

    # ── Aggregate ────────────────────────────────────────────────
    n = len(results)
    has_recall = [r for r in results if r["recall"].get("applicable")]
    n_src_full = sum(1 for r in has_recall if r["recall"]["source_full"])
    n_pages_full = sum(1 for r in has_recall if r["recall"]["pages_full"])
    n_eq = sum(1 for r in results if r["verdict"] == "EQUIVALENT")
    n_pa = sum(1 for r in results if r["verdict"] == "PARTIAL")
    n_di = sum(1 for r in results if r["verdict"] == "DIFFERENT")
    n_er = sum(1 for r in results if r["verdict"] == "ERROR")

    # MRR + nDCG averaged over questions where ground truth applies
    mrrs = [r["mrr_at_10"] for r in results if r["mrr_at_10"] is not None]
    ndcgs = [r["ndcg_at_10"] for r in results if r["ndcg_at_10"] is not None]
    avg_mrr = sum(mrrs) / len(mrrs) if mrrs else None
    avg_ndcg = sum(ndcgs) / len(ndcgs) if ndcgs else None

    # Judge medians + flip-rate
    rels = [r["judge"]["relevance"] for r in results if r["judge"]["relevance"] is not None]
    gnds = [r["judge"]["groundedness"] for r in results if r["judge"]["groundedness"] is not None]
    cits = [r["judge"]["citation_accuracy"] for r in results if r["judge"]["citation_accuracy"] is not None]
    flips = [r["judge"].get("flip_rate_relevance") for r in results
             if r["judge"].get("flip_rate_relevance") is not None]
    avg_rel = statistics.median(rels) if rels else None
    avg_gnd = statistics.median(gnds) if gnds else None
    avg_cit = statistics.median(cits) if cits else None
    avg_flip = sum(flips) / len(flips) if flips else None

    # Critical errors trend
    err_counter: dict[str, int] = {}
    for r in results:
        for e in r["judge"]["critical_errors"]:
            if e == "NONE":
                continue
            err_counter[e] = err_counter.get(e, 0) + 1

    # Citation accuracy aggregate
    cite_p_accs = [r["citation_validation"]["page_accuracy"]
                   for r in results
                   if r["citation_validation"] is not None
                   and r["citation_validation"]["page_accuracy"] is not None]
    avg_cite_pg = sum(cite_p_accs) / len(cite_p_accs) if cite_p_accs else None

    # Claim support is a DIFFERENT construct from page accuracy: the latter asks
    # "is this a real source and page", the former "does that chunk contain this
    # claim". Reported side by side, never blended.
    cs_vals = [(r.get("citation_claim_support") or {}).get("claim_support_avg")
               for r in results]
    cs_vals = [v for v in cs_vals if isinstance(v, (int, float))]
    avg_claim_support = sum(cs_vals) / len(cs_vals) if cs_vals else None
    cs_flips = [(r.get("citation_claim_support") or {}).get("flip_rate")
                for r in results]
    cs_flips = [v for v in cs_flips if isinstance(v, (int, float))]
    avg_cs_flip = sum(cs_flips) / len(cs_flips) if cs_flips else None

    # Print "n/a" rather than "0.0%" when no question carried a ranking metric.
    # A non-ranking arm reporting "0.0% recall" reads as a catastrophic result
    # instead of "this metric does not apply to this architecture".
    src_pct = (n_src_full / len(has_recall) * 100) if has_recall else None
    pg_pct = (n_pages_full / len(has_recall) * 100) if has_recall else None
    _pct = lambda v: f"{v:5.1f}%" if v is not None else "    n/a"        # noqa: E731
    eq_pct = (n_eq / n * 100) if n else 0.0
    eq_pa_pct = ((n_eq + n_pa) / n * 100) if n else 0.0

    summary_lines = [
        "=" * 78,
        f"RESULTS — {'HARD' if hard else 'easy'} eval  ({n} questions, {elapsed:.1f}s)",
        "=" * 78,
        f"Retrieval recall@{TOP_K} (source):  {_pct(src_pct)}  ({n_src_full}/{len(has_recall)})",
        f"Retrieval recall@{TOP_K} (pages):   {_pct(pg_pct)}  ({n_pages_full}/{len(has_recall)})",
        f"Retrieval MRR@{TOP_K}:              {avg_mrr:.3f}" if avg_mrr is not None else "Retrieval MRR@10:              n/a",
        f"Retrieval nDCG@{TOP_K}:             {avg_ndcg:.3f}" if avg_ndcg is not None else "Retrieval nDCG@10:             n/a",
        f"Answer correctness (EQUIVALENT):   {eq_pct:5.1f}%  ({n_eq}/{n})",
        f"  + partial credit:                {eq_pa_pct:5.1f}%  (+ {n_pa} PARTIAL)",
        f"  different:                       {n_di}",
        f"  errors:                          {n_er}",
        "─" * 78,
        f"Judge median relevance:           {avg_rel}/5" if avg_rel is not None else "Judge median relevance:           n/a",
        f"Judge median groundedness:        {avg_gnd}/5" if avg_gnd is not None else "Judge median groundedness:        n/a",
        f"Judge median citation_accuracy:   {avg_cit}/5" if avg_cit is not None else "Judge median citation_accuracy:   n/a",
        f"Judge mean flip-rate (relevance): {avg_flip:.3f}" if avg_flip is not None else "Judge mean flip-rate (relevance): n/a",
        f"Citation page-accuracy (avg):     {avg_cite_pg:.3f}" if avg_cite_pg is not None else "Citation page-accuracy (avg):     n/a",
        "─" * 78,
        "Critical errors:                  " + (
            ", ".join(f"{k}={v}" for k, v in sorted(err_counter.items())) if err_counter else "none"
        ),
        "=" * 78,
    ]
    summary = "\n" + "\n".join(summary_lines) + "\n"
    print(summary)

    if hard:
        print("Per-type breakdown:")
        types = sorted({r["question_type"] for r in results})
        for t in types:
            tres = [r for r in results if r["question_type"] == t]
            tn = len(tres)
            teq = sum(1 for r in tres if r["verdict"] == "EQUIVALENT")
            tpa = sum(1 for r in tres if r["verdict"] == "PARTIAL")
            t_mrr = [r["mrr_at_10"] for r in tres if r["mrr_at_10"] is not None]
            t_ndcg = [r["ndcg_at_10"] for r in tres if r["ndcg_at_10"] is not None]
            mrr_v = (sum(t_mrr) / len(t_mrr)) if t_mrr else 0.0
            ndcg_v = (sum(t_ndcg) / len(t_ndcg)) if t_ndcg else 0.0
            print(f"  {t:<12} {teq}/{tn} EQUIVALENT  ({tpa} PARTIAL)  MRR={mrr_v:.2f}  nDCG={ndcg_v:.2f}")
        print()

    # ── Persist ──────────────────────────────────────────────────
    out_json = Path(__file__).parent / f"{out_stem}.json"
    out_json.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "subset": holdout,
                "arm": arm,
                "arm_name": producer.name,
                "arm_config_hash": producer.config_hash(),
                "judge_runs": judge_runs,
                "judge_evidence": judge_evidence,
                # Without these the gate compares judge medians and critical-error
                # sets across two files scored under different rubrics and cannot
                # tell. Present in per-question traces already; the envelope is
                # what eval/gate.py actually reads.
                #
                # judge_prompt_hash covers the rubric TEXT; judge_code_hash covers
                # the judge logic. Neither subsumes the other, and a run needs both
                # to be comparable: the six-error clearance moved on prompts, the
                # h01 separator fix moved on code, and each left the other hash
                # untouched.
                "judge_prompt_hash": judge_prompt_hash,
                "judge_code_hash": jc_hash,
                "qa_prompt_hash": qa_prompt_hash,
                "use_rerank": use_rerank,
                "citation_support_runs": (support_runs if citation_support else None),
                "citation_support_scope": (
                    ("corpus_only" if arm == "C" else "own") if citation_support else None),
                "citation_support_prompt_version": (
                    CITATION_SUPPORT_PROMPT_VERSION if citation_support else None),
                "results": results,
            },
            indent=2, ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    subset_label = {
        "all": "all (tuning + holdout combined)",
        "tuning": "tuning only — develop here, then freeze before holdout",
        "holdout": "HOLDOUT only — quoted numbers go here",
    }.get(holdout, holdout)
    out_md = Path(__file__).parent / f"{out_stem}.md"
    md_lines = [
        f"# Eval Results — {'HARD' if hard else 'easy'}",
        "",
        f"Run ID: `{run_id}`",
        f"Subset: **{subset_label}**",
        # Loud, not a footnote: a no-rerank run misread as a rerank run would
        # silently attribute a retrieval-quality change to something else.
        *([] if use_rerank else ["", "> **RERANK DISABLED** (`--no-rerank`) — "
                                "retrieval is RRF order only. Not comparable to a "
                                "default run."]),
        "",
        summary.strip(),
        "",
        "## Per-question",
        "",
        "| ID | Type | recall src/pg | MRR | nDCG | rel/gnd/cit | cite-pg | Verdict | Question |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        rc = r["recall"]
        if rc.get("applicable"):
            recall_s = f"{'✓' if rc['source_full'] else '✗'}/{'✓' if rc['pages_full'] else '✗'}"
        else:
            recall_s = "—"
        mrr = r.get("mrr_at_10")
        ndcg = r.get("ndcg_at_10")
        mrr_s = f"{mrr:.2f}" if mrr is not None else "—"
        ndcg_s = f"{ndcg:.2f}" if ndcg is not None else "—"
        j = r["judge"]
        rgc = f"{j.get('relevance') or '—'}/{j.get('groundedness') or '—'}/{j.get('citation_accuracy') or '—'}"
        cv = r.get("citation_validation") or {}
        cite_pg = cv.get("page_accuracy")
        cite_s = f"{cite_pg:.2f}" if cite_pg is not None else "—"
        md_lines.append(
            f"| {r['id']} | {r['question_type']} | {recall_s} | {mrr_s} | {ndcg_s} | "
            f"{rgc} | {cite_s} | {r['verdict']} | {r['question'][:80]} |"
        )
    md_lines.append("")
    md_lines.append("## Failures (DIFFERENT, PARTIAL, ERROR, or critical error)")
    md_lines.append("")
    for r in results:
        crit = [e for e in r["judge"]["critical_errors"] if e != "NONE"]
        if r["verdict"] in ("DIFFERENT", "PARTIAL", "ERROR") or crit:
            md_lines.append(f"### {r['id']} — {r['verdict']}  ({r['question_type']})")
            md_lines.append(f"**Q:** {r['question']}")
            if r["must_cite_sources"]:
                md_lines.append(f"**Required sources:** {r['must_cite_sources']}")
            md_lines.append(f"**Recall:** {r['recall']}")
            md_lines.append(f"**MRR@10:** {r['mrr_at_10']}, **nDCG@10:** {r['ndcg_at_10']}")
            md_lines.append(f"**Judge:** {r['judge']}")
            md_lines.append(f"**Citation validation:** {r['citation_validation']}")
            md_lines.append(f"**Retrieved:** {[(t['source'], t['pages']) for t in r['retrieved']]}")
            md_lines.append(f"**Expected:** {r['expected_answer']}")
            md_lines.append(f"**Got:** {r['actual_answer'][:600]}{'...' if len(r['actual_answer']) > 600 else ''}")
            md_lines.append("")
    out_md.write_text("\n".join(md_lines), encoding="utf-8")

    print(f"Detailed results: {out_json}")
    print(f"Human summary:    {out_md}")
    print(f"Trace records:    data/traces/{trace_subdir}/")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--hard", action="store_true",
                        help="Load eval/questions_hard.json (page-level recall, type-specific judges).")
    parser.add_argument("--judge-runs", type=int, default=DEFAULT_JUDGE_RUNS,
                        help=f"How many judge calls per question for median aggregation (default {DEFAULT_JUDGE_RUNS}).")
    parser.add_argument("--run-id", default=None,
                        help="Override the auto-generated run ID (used for trace subdir).")
    parser.add_argument(
        "--holdout",
        choices=["all", "tuning", "holdout"],
        default="all",
        help="Run all questions, only tuning set, or only holdout. During development, "
             "use --holdout tuning. Before claiming metrics, run --holdout holdout once "
             "and freeze.",
    )
    parser.add_argument(
        "--arm", choices=["A", "B", "C"], default="A",
        help="Which architecture produces the answers. A = hybrid RAG (default, "
             "identical to pre-ablation behaviour). B and C arrive in Phase 2.",
    )
    parser.add_argument("--only", default=None,
                        help="Comma-separated question ids to run (e.g. h04,h07).")
    parser.add_argument("--resume", action="store_true",
                        help="Skip questions already checkpointed for this --run-id and arm.")
    parser.add_argument("--cache-dir", default=None,
                        help="Answer cache location (default data/answer_cache).")
    parser.add_argument("--no-cache", action="store_true",
                        help="Ignore and do not write the answer cache; always regenerate.")
    parser.add_argument(
        "--judge-evidence", choices=["own", "gold", "corpus"], default="own",
        help="What the LLM judge sees. 'own' = the arm's own context "
             "(faithfulness; reproduces pre-ablation semantics, but an arm with no "
             "shown context gets an empty block and a bogus groundedness of 1). "
             "'gold' = the question's gold passages (identical across arms, but "
             "penalises an arm that correctly reads beyond the chunk-shaped label). "
             "'corpus' = the whole corpus (label-independent and identical across "
             "arms; the defensible choice for cross-arm comparison, at ~294K chars "
             "per LLM-judged call).",
    )
    parser.add_argument("--mirror-dir", default=None,
                        help="Arm C only: corpus text mirror (default: outside the repo; "
                             "build with python tools/build_mirror.py).")
    parser.add_argument("--agentic-timeout", type=int, default=1800,
                        help="Arm C only: wall-clock seconds per question (default 1800). "
                             "CLI 2.1.92 has no --max-turns, so this is the main bound.")
    parser.add_argument("--agentic-output-format", choices=["json", "stream-json"],
                        default="json",
                        help="Arm C only: 'stream-json' also captures the tool-call trace.")
    parser.add_argument("--max-budget-usd", type=float, default=None,
                        help="Arm C only: per-question spend cap passed to the CLI.")
    parser.add_argument("--no-rerank", action="store_true",
                        help="Arm A only: skip the cross-encoder rerank. Recorded in the "
                             "results envelope and MD header so a no-rerank run can never "
                             "be read as a rerank run.")
    parser.add_argument("--no-citation-support", action="store_true",
                        help="Skip the claim-to-citation support scorer (saves ~3 CLI "
                             "calls per question; the metric is reported, never gated).")
    parser.add_argument("--support-runs", type=int, default=CITATION_SUPPORT_RUNS,
                        help=f"Adjudicator runs per citation (default {CITATION_SUPPORT_RUNS}).")
    parser.add_argument("--support-cache-dir", default=None,
                        help="Citation-support cache location.")
    parser.add_argument("--out-suffix", default="",
                        help="Appended to the results filename. Use for repeat-sample "
                             "runs (e.g. --out-suffix seed2) so a second generation "
                             "seed does not overwrite the first one's results.")
    args = parser.parse_args()
    if args.resume and not args.run_id:
        # The checkpoint file is named after the run id; without it --resume would
        # silently open a fresh file and re-run everything at full cost.
        parser.error("--resume requires --run-id (the id printed by the run you are resuming)")
    run_eval(
        hard=args.hard, judge_runs=args.judge_runs, run_id=args.run_id,
        holdout=args.holdout, arm=args.arm, cache_dir=args.cache_dir,
        use_cache=not args.no_cache, resume=args.resume, only=args.only,
        judge_evidence=args.judge_evidence,
        mirror_dir=args.mirror_dir, agentic_timeout=args.agentic_timeout,
        agentic_output_format=args.agentic_output_format,
        max_budget_usd=args.max_budget_usd,
        out_suffix=args.out_suffix,
        use_rerank=not args.no_rerank,
        citation_support=(CITATION_SUPPORT_ENABLED and not args.no_citation_support),
        support_runs=args.support_runs,
        support_cache_dir=args.support_cache_dir,
    )
