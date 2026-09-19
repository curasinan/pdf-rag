"""Claim-to-citation support: does the cited chunk actually contain this claim?

`citations.validate_citations` answers a different and much weaker question. It
marks a citation valid when its page range overlaps ANY retrieved chunk of that
source, so it measures "you named a real source and a page you were shown" — a
fabrication check. It never sees the claim the citation is attached to. That is
why one answer scored ``page_accuracy 1.0`` while two of three judge runs called
it CITATION_WRONG: the opening sentence cited the summary chunk while describing
content that lives four pages earlier.

This module adds the attribution check beside it. Five stages, and only stage 4
touches an LLM:

1. occurrences   - every citation marker, with offsets (``citations``)
2. attribution   - the span of answer text each marker terminates  (deterministic)
3. resolution    - the chunk text that marker points at             (deterministic)
4. support       - does that text support that claim?               (LLM, injected)
5. verification  - is each SUPPORTED part's quote really in the evidence? (deterministic)

Design decisions that are load-bearing, each made because the alternative was
measured failing:

- **The score is a mean support FRACTION, never a conjunctive label.** One answer
  packs ten sub-claims under a single citation; under "every part must be
  SUPPORTED" a single false negative zeroes a correct citation, and the false
  negative rate compounds with window length.
- **Evidence is the UNION of every chunk whose pages intersect the citation**, not
  the best-matching one. An argmax needs a tie-break, and adjacent chunks share a
  boundary page by construction, so the tie-break decides scores by list order.
- **Quote verification is fail-closed on TOKEN RECALL, not exact substring.**
  docling physically reorders text; correct verbatim quotes are routinely absent
  as substrings from their own source chunk. See ``verify_quote``.

What this does NOT measure is in CLAUDE.md under Known Limitations. The short
version: it only sees spans that carry a citation, union resolution makes it blind
to page-level precision, and the LLM stage is uncalibrated against human labels.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from pathlib import Path
from typing import Callable, Iterable

from config import (
    CITATION_CLAIM_MAX_CHARS,
    CITATION_CLAIM_MIN_ALNUM,
    CITATION_MIN_CLAIM_TOKENS,
    CITATION_QUOTE_MIN_TOKEN_RECALL,
    CITATION_QUOTE_RARE_DF_FRACTION,
    CITATION_SUPPORT_MAX_PARTS,
    CITATION_SUPPORT_PROMPT_VERSION,
    CITATION_SUPPORT_RUNS,
)
from citations import (_coerce_pages_field, _source_matches, citation_occurrences,
                       nfc_answer)

# ── Tokenisation ─────────────────────────────────────────────────────

_TOKEN_RE = re.compile(r"[0-9]+(?:[.,][0-9]+)*|[^\W\d_]+", re.UNICODE)

# Function words carry no evidential weight; a quote must not verify on them alone.
_STOP = frozenset("""
a an the and or but if then than that this these those of in on at to for from by with
as is are was were be been being it its it's do does did not no nor so such can could
may might will would shall should must have has had you your they them their we our us
i he she his her which who whom what when where why how all any both each few more most
other some only own same too very s t just also into about over under again further once
""".split())


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(unicodedata.normalize("NFC", text or ""))]


def _content_tokens(text: str) -> list[str]:
    return [t for t in _tokens(text) if t not in _STOP and len(t) > 1]


# ── IDF over the corpus ──────────────────────────────────────────────


def build_idf(chunks: Iterable[dict]) -> dict:
    """Document frequency over CHUNKS, used only to decide which tokens are rare.

    Corpus-level, never evidence-level: in a single-domain corpus the domain words
    ("coffee", "shop", "costs") appear in nearly every chunk, and they are exactly
    the tokens that let a miscitation look supported.
    """
    df: dict[str, int] = {}
    n = 0
    for c in chunks:
        n += 1
        for t in set(_content_tokens(c.get("text") or "")):
            df[t] = df.get(t, 0) + 1
    return {"n": max(1, n), "df": df}


def _idf(idf: dict, token: str) -> float:
    n = idf.get("n", 1)
    d = idf.get("df", {}).get(token, 0)
    # A token appearing nowhere in the corpus gets the maximum score: a claim term
    # that exists in no chunk is maximally suspicious, which is the right prior.
    return math.log((n + 1) / (d + 1)) + 1.0


def _is_rare(idf: dict, token: str) -> bool:
    n = idf.get("n", 1)
    return idf.get("df", {}).get(token, 0) <= max(1, int(CITATION_QUOTE_RARE_DF_FRACTION * n))


# ── Stage 5: quote verification (deterministic) ──────────────────────


def verify_quote(quote: str, evidence: str, idf: dict | None = None) -> str:
    """Is this quote really drawn from this evidence? Returns "exact"|"fuzzy"|"none".

    NOT a plain substring test, deliberately. The PDF backend reorders text when it
    reconstructs reading order, so a model quoting a source correctly can produce a
    string that is not a substring of the chunk it came from. Requiring exact
    containment therefore rejects correct citations — measured on real answers.

    Instead: token recall of the quote against the evidence must clear
    ``CITATION_QUOTE_MIN_TOKEN_RECALL``, AND the quote's rarest content token must
    be present, so a quote cannot pass on common words alone.

    This is a FABRICATION guard, not a correctness guarantee. A model that reorders
    a source's own words into a claim the source does not make will pass here; only
    the LLM stage can catch that, and imperfectly.
    """
    q = (quote or "").strip()
    if not q:
        return "none"
    ev = unicodedata.normalize("NFC", evidence or "")
    if q.lower() in ev.lower():
        return "exact"
    qt = _content_tokens(q)
    if not qt:
        return "none"
    ev_set = set(_content_tokens(ev))
    recall = sum(1 for t in set(qt) if t in ev_set) / len(set(qt))
    if recall < CITATION_QUOTE_MIN_TOKEN_RECALL:
        return "none"
    if idf:
        rare = [t for t in set(qt) if _is_rare(idf, t)]
        if rare:
            rarest = max(rare, key=lambda t: _idf(idf, t))
            if rarest not in ev_set:
                return "none"
    return "fuzzy"


# ── Stage 2: claim attribution (deterministic) ───────────────────────

_BLOCK_START = re.compile(r"^\s*(?:[-*+]\s|\d+[.)]\s|#{1,6}\s|\*\*)")
_SENT_END = re.compile(r"(?<=[.!?:])\s+")


def _boundaries(text: str) -> list[int]:
    """Block starts (blank line, bullet, heading) plus sentence ends."""
    bounds = {0}
    pos = 0
    for line in text.splitlines(keepends=True):
        if _BLOCK_START.match(line) or not line.strip():
            bounds.add(pos)
        pos += len(line)
    for m in _SENT_END.finditer(text):
        bounds.add(m.end())
    return sorted(bounds)


def attribute_claims(answer: str, occurrences: list[dict] | None = None) -> list[dict]:
    """Map each citation occurrence to the span of text it terminates.

    A citation marker sits at the END of the claim it supports — that is what the
    pinned context-header format teaches the model to do. Not universal: some
    answers put a marker mid-sentence, which is the main source of attribution
    error in this metric.
    """
    a = nfc_answer(answer)
    occ = occurrences if occurrences is not None else citation_occurrences(answer)
    bounds = _boundaries(a)
    spans = [tuple(o["span"]) for o in occ]

    out: list[dict] = []
    prev_end = 0
    for i, o in enumerate(occ):
        s, e = o["span"]
        # Strictly `< s`: a sentence boundary can land exactly on the "[", and
        # `<= s` would collapse every bullet in a list into one window.
        cands = [b for b in bounds if prev_end <= b < s]
        start = max(cands) if cands else prev_end
        window = a[start:s]
        # Drop any other citation markers that fall inside the window.
        for (cs, ce) in spans:
            if cs >= start and ce <= s:
                window = window.replace(a[cs:ce], " ")
        window = window.strip()
        if len(window) > CITATION_CLAIM_MAX_CHARS:
            window = window[-CITATION_CLAIM_MAX_CHARS:]   # keep the end, nearest the marker
        alnum = sum(1 for ch in window if ch.isalnum())
        rec = {
            "citation_index": o["citation_index"],
            "span": o["span"],
            "source": o["source"],
            "pages": o["pages"],
            "raw": o["raw"],
            "claim": window,
            "co_cited_with": None,
        }
        # Back-to-back markers: "…text [Doc A, page 3][Doc B, pages 1-3]". The second
        # marker's window is empty for a structural reason, not a quality one, so it
        # joins the previous occurrence and their evidence is unioned.
        if alnum < CITATION_CLAIM_MIN_ALNUM and out:
            rec["claim"] = out[-1]["claim"]
            rec["co_cited_with"] = len(out) - 1
        out.append(rec)
        prev_end = e
    return out


# ── Stage 3: evidence resolution (deterministic) ─────────────────────


def resolve_evidence(citation: dict, chunks: list[dict]) -> tuple[str, list[str], str]:
    """Resolve a citation to chunk text. Returns (evidence_text, chunk_ids, grade).

    Evidence is the UNION of every candidate chunk whose pages intersect the cited
    pages — never a best match. Adjacent chunks share a boundary page by
    construction, so any argmax is decided by a tie-break, and a tie-break decided
    by list order silently picks the chunk without the numbers in it.

    Grades are diagnostics only and never affect the score. SUBSET in particular
    must never be penalised: it is what an arm citing a precise page inside a
    multi-page chunk correctly produces.
    """
    cited = set(citation.get("pages") or [])
    cands = [c for c in chunks if _source_matches(citation.get("source", ""), c.get("source", ""))]
    if not cands:
        return "", [], "UNRESOLVED_SOURCE"
    if not cited:
        # Source named with no pages: the whole source is the evidence.
        return ("\n\n".join(c.get("text") or "" for c in cands),
                [c.get("id") for c in cands if c.get("id")], "OVERLAP")

    hits, grade = [], "OVERLAP"
    exact = subset = False
    for c in cands:
        # ChromaDB stores `pages` as the string repr of a list, not a list. Coercing
        # through the shared helper matters: `set("[24, 25]")` is a set of CHARACTERS
        # and silently resolves every citation to nothing.
        pages = set(_coerce_pages_field(c.get("pages")))
        if not pages & cited:
            continue
        hits.append(c)
        if pages == cited:
            exact = True
        elif cited < pages:
            subset = True
    if not hits:
        return "", [], "UNRESOLVED_PAGES"
    if exact:
        grade = "EXACT"
    elif subset:
        grade = "SUBSET"
    elif len(hits) > 1:
        grade = "SPANNING"
    return ("\n\n".join(c.get("text") or "" for c in hits),
            [c.get("id") for c in hits if c.get("id")], grade)


# ── Stage 4: the adjudicator (the only LLM stage) ────────────────────

SUPPORT_SYSTEM = (
    "You check whether a passage of evidence supports the claims attached to one "
    "citation. Use ONLY the EVIDENCE. Reply with a single JSON object, nothing else, "
    "no code fences, no preamble."
)

SUPPORT_USER = """EVIDENCE (the text the citation points at):
{evidence}

CLAIM WINDOWS attached to this citation (one per line, numbered):
{windows}

For EACH window, decompose it into at most {max_parts} CHECKABLE assertions and decide
whether the EVIDENCE supports each one.

Rules:
- An enumeration is ONE part unless its items are independently verifiable.
- Discourse, framing and connective text ("both documents", "in short", "the argument")
  is NOT a checkable part. Do not emit it.
- The EVIDENCE may span several pages and may contain extraction artifacts
  (`<!-- image -->`, sentence fragments out of order, split paragraphs). Text that is
  reassembled or lightly reworded is NOT evidence of fabrication.
- A comparison or summary drawn from the EVIDENCE is SUPPORTED. A claim the EVIDENCE
  does not contain is UNSUPPORTED, even if it is plausible.
- Every SUPPORTED part MUST carry "quote": a verbatim span copied from the EVIDENCE.
  If you cannot copy one, the part is UNSUPPORTED.

Output exactly this JSON:
{{"windows":[{{"index":<int>,"parts":[{{"text":"<the assertion>","verdict":"SUPPORTED"|"UNSUPPORTED","quote":"<verbatim from EVIDENCE, or empty>"}}]}}]}}"""


def _parse_support_json(raw: str) -> list[dict] | None:
    if not raw:
        return None
    t = raw.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n?", "", t)
        t = re.sub(r"\n?```$", "", t).strip()
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j <= i:
        return None
    try:
        data = json.loads(t[i:j + 1])
    except json.JSONDecodeError:
        return None
    wins = data.get("windows")
    return wins if isinstance(wins, list) else None


def llm_adjudicator(model: str | None = None,
                    timeout: int = 240) -> Callable[[str, list[str]], list[dict] | None]:
    """Real adjudicator. Imported lazily so this module stays LLM-free to import.

    ``timeout`` defaults well below ``call_claude``'s 900s: these prompts are ~16K
    chars and answer in seconds, so a call still running after four minutes has
    hung rather than being slow, and 900s turns one hang into a quarter-hour stall.
    A timeout returns None, which the caller records as ERROR for that citation
    rather than as a support failure.
    """
    def _call(evidence: str, windows: list[str]) -> list[dict] | None:
        from claude_bridge import call_claude, ClaudeCLIError
        from config import CITATION_SUPPORT_MODEL
        numbered = "\n".join(f"{i}. {w}" for i, w in enumerate(windows))
        try:
            raw = call_claude(
                model=model or CITATION_SUPPORT_MODEL,
                system=SUPPORT_SYSTEM,
                user=SUPPORT_USER.format(evidence=evidence, windows=numbered,
                                         max_parts=CITATION_SUPPORT_MAX_PARTS),
                temperature=0.0,          # verifier-style call; project convention
                timeout=timeout,
            )
        except ClaudeCLIError:
            return None
        return _parse_support_json(raw)
    return _call


# ── Scoring ──────────────────────────────────────────────────────────


def _cache_key(source: str, pages, windows: list[str], evidence: str, run: int) -> str:
    blob = json.dumps({
        "v": CITATION_SUPPORT_PROMPT_VERSION, "source": source, "pages": list(pages or []),
        "windows": windows, "evidence_sha": hashlib.sha1(evidence.encode("utf-8")).hexdigest(),
        "run": run,
    }, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


def score_citation_support(
    answer: str,
    chunks: list[dict],
    *,
    scope: str = "own",
    runs: int = CITATION_SUPPORT_RUNS,
    adjudicator: Callable[[str, list[str]], list[dict] | None] | None = None,
    idf: dict | None = None,
    cache_dir: str | Path | None = None,
) -> dict:
    """Score every citation occurrence in ``answer`` against the chunks it names.

    ``adjudicator`` is injected so the deterministic stages are testable without an
    LLM. Pass ``llm_adjudicator()`` for the real thing.
    """
    occ = citation_occurrences(answer)
    claims = attribute_claims(answer, occ)
    idf = idf if idf is not None else build_idf(chunks)
    adj = adjudicator if adjudicator is not None else llm_adjudicator()
    cache_path = Path(cache_dir) if cache_dir else None

    # Group occurrences by deduped citation: one LLM call carries every window of
    # one citation together with its evidence.
    groups: dict[int, list[int]] = {}
    for i, c in enumerate(claims):
        groups.setdefault(c["citation_index"], []).append(i)

    # Co-citation partners. "…text [Doc A, page 3][Doc B, pages 1-3]" attaches ONE
    # claim to two citations, so each must be scored against the UNION of both
    # chunks. Sharing only the window (and not the evidence) makes the second
    # citation fail for a structural reason: it is asked about a claim its own
    # chunk was never meant to carry alone.
    partners: dict[int, set[int]] = {}
    for i, c in enumerate(claims):
        j = c.get("co_cited_with")
        if j is None:
            continue
        a, b = c["citation_index"], claims[j]["citation_index"]
        if a == b:
            continue
        partners.setdefault(a, set()).add(b)
        partners.setdefault(b, set()).add(a)

    per_occ: list[dict] = [None] * len(claims)      # type: ignore[list-item]
    llm_calls = cache_hits = 0
    n_exact = n_fuzzy = n_rejected = 0
    per_citation = []

    for cid, idxs in sorted(groups.items()):
        head = claims[idxs[0]]
        evidence, chunk_ids, grade = resolve_evidence(head, chunks)
        for pcid in sorted(partners.get(cid, ())):
            phead = next((c for c in claims if c["citation_index"] == pcid), None)
            if phead is None:
                continue
            pev, pids, _ = resolve_evidence(phead, chunks)
            if pev:
                evidence = (evidence + "\n\n" + pev) if evidence else pev
                chunk_ids = chunk_ids + [x for x in pids if x not in chunk_ids]
                if grade in ("UNRESOLVED_SOURCE", "UNRESOLVED_PAGES"):
                    grade = "SPANNING"      # the pair resolves even if this one alone did not

        if grade in ("UNRESOLVED_SOURCE", "UNRESOLVED_PAGES"):
            for i in idxs:
                per_occ[i] = {"label": "NONE", "support_fraction": 0.0, "parts": [],
                              "resolution": grade, "reason": "unresolved"}
            per_citation.append({"raw": head["raw"], "source": head["source"],
                                 "pages": head["pages"], "resolution": grade,
                                 "label": "NONE", "score": 0.0, "chunk_ids": []})
            continue

        # ABSTAIN: too little text to judge. Contributes to neither numerator nor
        # denominator — folding it in as 0.0 would be a lie.
        scorable = [i for i in idxs
                    if len(_content_tokens(claims[i]["claim"])) >= CITATION_MIN_CLAIM_TOKENS]
        for i in idxs:
            if i not in scorable:
                per_occ[i] = {"label": "ABSTAIN", "support_fraction": None, "parts": [],
                              "resolution": grade, "reason": "claim too short"}
        if not scorable:
            per_citation.append({"raw": head["raw"], "source": head["source"],
                                 "pages": head["pages"], "resolution": grade,
                                 "label": "ABSTAIN", "score": None, "chunk_ids": chunk_ids})
            continue

        windows = [claims[i]["claim"] for i in scorable]
        run_fracs: dict[int, list[float]] = {i: [] for i in scorable}
        run_parts: dict[int, list[dict]] = {i: [] for i in scorable}

        for run in range(max(1, runs)):
            payload = None
            key = _cache_key(head["source"], head["pages"], windows, evidence, run)
            fp = (cache_path / f"{key}.json") if cache_path else None
            if fp is not None and fp.exists():
                try:
                    payload = json.loads(fp.read_text(encoding="utf-8")).get("windows")
                    cache_hits += 1
                except Exception:
                    payload = None
            if payload is None:
                payload = adj(evidence, windows)
                llm_calls += 1
                if payload is not None and fp is not None:
                    fp.parent.mkdir(parents=True, exist_ok=True)
                    tmp = fp.with_suffix(".tmp")
                    tmp.write_text(json.dumps({"windows": payload}, ensure_ascii=False),
                                   encoding="utf-8")
                    tmp.replace(fp)
            if not payload:
                continue
            by_index = {}
            for w in payload:
                if isinstance(w, dict) and isinstance(w.get("index"), int):
                    by_index[w["index"]] = w.get("parts") or []
            for pos, i in enumerate(scorable):
                parts = by_index.get(pos, [])
                checked = []
                # Score every returned part. CITATION_SUPPORT_MAX_PARTS is a
                # PROMPT-level cap, never a slice here: truncating the list drops
                # whatever the model put last, and an UNSUPPORTED part in the tail
                # would silently vanish and bias the fraction upward.
                for p in parts:
                    if not isinstance(p, dict):
                        continue
                    verdict = str(p.get("verdict", "")).upper().strip()
                    quote = str(p.get("quote", "") or "")
                    qm = "none"
                    if verdict == "SUPPORTED":
                        qm = verify_quote(quote, evidence, idf)
                        if qm == "none":
                            # Fail closed: a SUPPORTED part whose quote is not in the
                            # evidence is demoted. This is the one guarantee here that
                            # does not depend on the model's judgement.
                            verdict = "UNSUPPORTED"
                            n_rejected += 1
                        elif qm == "exact":
                            n_exact += 1
                        else:
                            n_fuzzy += 1
                    checked.append({"text": str(p.get("text", ""))[:400],
                                    "verdict": verdict, "quote": quote[:300],
                                    "quote_match": qm})
                if checked:
                    frac = sum(1 for c in checked if c["verdict"] == "SUPPORTED") / len(checked)
                    run_fracs[i].append(frac)
                    if not run_parts[i]:
                        run_parts[i] = checked

        for i in scorable:
            fr = run_fracs[i]
            if not fr:
                per_occ[i] = {"label": "ERROR", "support_fraction": None, "parts": [],
                              "resolution": grade, "reason": "adjudicator returned nothing"}
                continue
            mean = sum(fr) / len(fr)
            label = "FULL" if mean >= 1.0 else ("NONE" if mean <= 0.0 else "PARTIAL")
            per_occ[i] = {"label": label, "support_fraction": mean, "parts": run_parts[i],
                          "resolution": grade, "runs": fr}

        scored = [per_occ[i]["support_fraction"] for i in scorable
                  if per_occ[i].get("support_fraction") is not None]
        per_citation.append({
            "raw": head["raw"], "source": head["source"], "pages": head["pages"],
            "resolution": grade, "chunk_ids": chunk_ids,
            "n_occurrences": len(idxs),
            "score": (sum(scored) / len(scored)) if scored else None,
            "label": (per_occ[scorable[0]] or {}).get("label"),
        })

    scored_vals = [o["support_fraction"] for o in per_occ
                   if o and o.get("support_fraction") is not None]
    flips = 0
    pairs = 0
    for o in per_occ:
        rs = (o or {}).get("runs") or []
        for x, y in zip(rs, rs[1:]):
            pairs += 1
            if x != y:
                flips += 1

    return {
        "claim_support_avg": (sum(scored_vals) / len(scored_vals)) if scored_vals else None,
        "n_occurrences": len(claims),
        "n_scored": len(scored_vals),
        "n_abstained": sum(1 for o in per_occ if o and o.get("label") == "ABSTAIN"),
        "n_unresolved": sum(1 for o in per_occ if o and o.get("reason") == "unresolved"),
        "support_scope": scope,
        "support_runs": runs,
        "prompt_version": CITATION_SUPPORT_PROMPT_VERSION,
        "llm_calls": llm_calls,
        "cache_hits": cache_hits,
        "n_quote_exact": n_exact,
        "n_quote_fuzzy": n_fuzzy,
        "n_quote_rejected": n_rejected,
        "flip_rate": (flips / pairs) if pairs else 0.0,
        "per_citation": per_citation,
        "per_occurrence": per_occ,
    }
