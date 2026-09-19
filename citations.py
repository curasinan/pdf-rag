"""Citation parsing + validation (Weekend-3 Phase A3).

The book's Chapter 6 §6.5 + Case F.1 demand: every factual claim in an answer
must be traceable to a chunk that was actually retrieved, on a page the model
could have seen. Without this validator the pipeline fails silently when the
chunker re-segments and the model "cites" a page that no longer matches the
retrieved chunk text.

What this module does
=====================
1. parse_citations(answer: str) -> list[dict]
   Pull citation markers out of free-text answers. The QA prompt is loose, so
   models produce a variety of shapes: "[Source Name, pages 4-5]", "(source
   name, p. 7)", "page 12 of the X document", "according to the Y manual on
   pages 3-4", etc. The parser is deliberately tolerant: it returns best-effort
   extracted (source_hint, pages) tuples and lets the validator decide whether
   they correspond to anything real.

2. validate_citations(parsed, retrieved) -> dict
   For each parsed citation, check:
     - source_exists: does any retrieved chunk have a source name that matches?
     - page_matches: of those, does at least one chunk's `pages` list overlap
       with the cited pages?
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any


# ── Normalization ────────────────────────────────────────────────────


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s) if isinstance(s, str) else s


# Typographic punctuation the PDF/DOCX extractors preserve in stored source names
# but that a model retypes in ASCII. Folding these is the same class of fix as the
# NFD/NFC gold-source repair: without it, a citation to
# `…Franchise's Performance` (ASCII apostrophe) fails to match the stored
# `…Franchise’s Performance` (U+2019) and resolves to nothing at all.
_TYPOGRAPHIC = str.maketrans({
    "‘": "'", "’": "'",          # single quotes
    "“": '"', "”": '"',          # double quotes
    "–": "-", "—": "-",          # en / em dash
    "…": "...",                       # ellipsis
    " ": " ",                         # non-breaking space
})


def _normalize_source(s: str) -> str:
    """Lowercase, NFC-normalize, fold typographic punctuation, strip surrounds."""
    if not s:
        return ""
    s = _nfc(s).lower().translate(_TYPOGRAPHIC).strip()
    s = re.sub(r"^[\"'\[\(\s]+", "", s)
    s = re.sub(r"[\"'\]\)\s.,]+$", "", s)
    return s


# ── Page parsing ─────────────────────────────────────────────────────


def _expand_pages(pages_str: str) -> list[int]:
    """Convert "4", "4-5", "4, 5, 7", "8-11" into a flat sorted unique int list."""
    out = set()
    if not pages_str:
        return []
    for piece in re.split(r"[,;]", pages_str):
        piece = piece.strip()
        if not piece:
            continue
        m = re.match(r"^(\d+)\s*[-–—]\s*(\d+)$", piece)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if a > b:
                a, b = b, a
            for p in range(a, b + 1):
                out.add(p)
            continue
        m = re.match(r"^(\d+)$", piece)
        if m:
            out.add(int(m.group(1)))
    return sorted(out)


def _coerce_pages_field(raw: Any) -> list[int]:
    """vectorstore stores `pages` as `str(list)` (e.g. "[1, 2, 3]"). Decode."""
    if isinstance(raw, list):
        try:
            return [int(x) for x in raw]
        except (TypeError, ValueError):
            return []
    if isinstance(raw, int):
        return [raw]
    if not isinstance(raw, str):
        return []
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1]
        out = []
        for piece in inner.split(","):
            piece = piece.strip()
            if not piece:
                continue
            try:
                out.append(int(piece))
            except ValueError:
                pass
        return out
    try:
        return [int(raw)]
    except ValueError:
        return []


def format_pages_human(raw: Any) -> str:
    """Render a stored pages field ("[1, 2, 3]", [4,5], 7) as a compact, human /
    parser-friendly string: "1-3", "4, 5", "7". Consecutive runs are collapsed to
    ranges.

    Why (finding F10): the context header the model is shown is the only citation
    format it learns. Rendering the raw stored value produced "pages [1, 2, 3]"
    (bracket-in-bracket), which ``parse_citations`` cannot parse — so a faithfully
    cited answer scored zero citations and corrupted the citation metrics. This
    produces a form pattern 1 of ``_CITATION_PATTERNS`` parses cleanly.
    """
    pages = _coerce_pages_field(raw)
    if not pages:
        return str(raw) if raw not in (None, "") else "?"
    pages = sorted(set(pages))
    runs: list[str] = []
    start = prev = pages[0]
    for p in pages[1:]:
        if p == prev + 1:
            prev = p
            continue
        runs.append(str(start) if start == prev else f"{start}-{prev}")
        start = prev = p
    runs.append(str(start) if start == prev else f"{start}-{prev}")
    return ", ".join(runs)


# ── Citation extraction ──────────────────────────────────────────────


_CITATION_PATTERNS = [
    # [Source, pages [1, 2, 3]] — legacy header shape (pages rendered as a Python
    # list). Kept for backward-compat with traces recorded before F10; tried first
    # so span-dedup prefers it over the general bracket pattern.
    re.compile(
        r"\[\s*(?P<src>[^\[\]]+?)[,\s]+(?:pages?|p\.?|pp\.?)\s*\[\s*(?P<pgs>[\d\s,\-–—]+?)\s*\]\s*\]",
        re.IGNORECASE,
    ),
    # [Source, pages 4-5] / [Source, page 7]
    re.compile(
        r"\[\s*(?P<src>[^\[\]]+?)[,\s]+(?:pages?|p\.?|pp\.?)\s*(?P<pgs>[\d\s,\-–—]+)\s*\]",
        re.IGNORECASE,
    ),
    # (Source, pages 4-5) / (Source, page 7)
    re.compile(
        r"\(\s*(?P<src>[^\(\)]+?)[,\s]+(?:pages?|p\.?|pp\.?)\s*(?P<pgs>[\d\s,\-–—]+)\s*\)",
        re.IGNORECASE,
    ),
    # "page 8 of (the) Source" / "pages 4-5 of Source".
    # The source may start with a digit: three of this corpus's 24 sources do
    # ("5 KPIs …", "7 Costs …", "7 Ways …"), and the old [A-Z'] class silently
    # dropped every prose citation to them.
    re.compile(
        r"(?:pages?|p\.?|pp\.?)\s*(?P<pgs>\d[\d\s,\-–—]*)\s+of\s+(?:the\s+)?(?P<src>[\w'][\w\s'’&\-\(\)\.]{2,120}?)(?=[\.,;\)\n]|$)",
        re.IGNORECASE,
    ),
    # "Source, pages 4-5" inline (no brackets) - lowest specificity.
    # The comma is REQUIRED. It used to be `[,\s]+`, which allowed
    # whitespace-only separation and therefore turned any capitalised prose
    # followed by a page number into a citation — "the RevPASH section on
    # page 5" parsed as source="RevPASH section on". Those phantom citations
    # land in the precision metric (an unmatchable source scores invalid), so a
    # fluent, prose-heavy answer was penalised for its writing style. Arms differ
    # in how chatty they are, which made this differentially unfair.
    re.compile(
        r"(?P<src>[^\W_][\w\s'’&\-\(\)\.]{2,120}?)\s*,\s*(?:pages?|p\.?|pp\.?)\s*(?P<pgs>\d[\d\s,\-–—]*)",
    ),
]

#: Indices of the unbracketed, heuristic patterns above. A bracketed or
#: parenthesised citation is an explicit act by the model and is trusted as-is;
#: these two infer a citation from running prose and need a plausibility floor.
_LOOSE_PATTERN_IDX = {3, 4}

#: Minimum alphabetic characters for a source inferred from prose. Rejects
#: "In 2024, page 5" (a date, not a document) while keeping every real source in
#: this corpus — the shortest is well above this.
_MIN_LOOSE_SRC_ALPHA = 4


_PAGE_ONLY_PATTERNS = [
    re.compile(r"\bpages?\s+(?P<pgs>\d[\d\s,\-–—]*)\b", re.IGNORECASE),
    re.compile(r"\bp\.?\s*(?P<pgs>\d+(?:\s*[-–—]\s*\d+)?)\b", re.IGNORECASE),
]


def parse_citations(answer: str) -> list[dict]:
    """Extract citation candidates from a free-text answer.

    Returns a list of {"source": str, "pages": list[int], "raw": str} dicts.
    Span-deduped: a less-specific pattern that matches inside a span already
    consumed by a more-specific pattern is skipped.
    """
    if not answer:
        return []
    a = _nfc(answer)
    consumed: list[tuple[int, int]] = []
    seen_keys: set[tuple[str, tuple[int, ...]]] = set()
    by_key: dict[tuple[str, tuple[int, ...]], dict] = {}
    out: list[dict] = []

    for pat_idx, pat in enumerate(_CITATION_PATTERNS):
        for m in pat.finditer(a):
            s, e = m.start(), m.end()
            # Span-overlap check: skip if any prior accepted match covers this span
            overlapped = False
            for cs, ce in consumed:
                if s < ce and e > cs:
                    overlapped = True
                    break
            if overlapped:
                continue
            src = (m.group("src") or "").strip()
            pgs = _expand_pages(m.group("pgs") or "")
            if not src:
                continue
            # Source names may start with a digit ("5 KPIs …"), but a citation
            # inferred from prose needs a plausibility floor, or a date reference
            # like "In 2024, page 5" becomes a phantom citation that counts
            # against precision.
            if pat_idx in _LOOSE_PATTERN_IDX:
                if sum(ch.isalpha() for ch in src) < _MIN_LOOSE_SRC_ALPHA:
                    continue
            elif not any(ch.isalpha() for ch in src):
                continue
            # Claim the span BEFORE the duplicate check. A repeated citation is
            # deduplicated from the output, but its text is still "spoken for" —
            # if the span were left unclaimed, a looser later pattern would match
            # a fragment inside it. That is exactly how the third occurrence of
            # "[5 KPIs … Manager Should Track, page 8]" produced a phantom
            # citation with source="Manager Should Track", which then passed
            # validation via substring matching and inflated the citation count.
            consumed.append((s, e))
            key = (_normalize_source(src), tuple(pgs))
            if key in seen_keys:
                # Still deduplicated from the output — `n_citations` is the
                # denominator of the gate-tracked citation_page_accuracy_avg and
                # must not move. But each OCCURRENCE attaches to a different
                # claim, so record its span on the entry already emitted: one
                # answer cites the same chunk on five separate bullets.
                by_key[key]["spans"].append([s, e])
                continue
            seen_keys.add(key)
            entry = {"source": src.strip(" .,;"), "pages": pgs,
                     "raw": m.group(0), "spans": [[s, e]]}
            by_key[key] = entry
            out.append(entry)

    return out


def citation_occurrences(answer: str) -> list[dict]:
    """Flatten :func:`parse_citations` into one record per OCCURRENCE, in document order.

    Derived from the single parse rather than a second matcher, so the two cannot
    drift apart.

    Offsets index ``nfc_answer(answer)``, **not** the raw string. Slicing the raw
    answer shifts every position once an NFD source name (``5 KPIs …Café…``) appears
    earlier in the text.
    """
    a = _nfc(answer)
    occ = []
    for i, c in enumerate(parse_citations(answer)):
        for (s, e) in c.get("spans", []):
            # Slice per occurrence rather than reusing the entry's ``raw``. Two
            # occurrences of one citation can be matched by DIFFERENT patterns —
            # a bracketed "[Top Metrics, pages 1-3]" and a bare prose mention
            # dedupe to the same key — so the entry's raw is only the first one's.
            occ.append({"citation_index": i, "span": [s, e], "source": c["source"],
                        "pages": c["pages"], "raw": a[s:e]})
    occ.sort(key=lambda o: o["span"][0])
    return occ


# Public alias: callers slicing citation offsets must normalize the answer the same
# way the parser did, or the offsets are meaningless.
nfc_answer = _nfc


def parse_page_only_mentions(answer: str) -> list[list[int]]:
    """Pages mentioned without an attached source name."""
    if not answer:
        return []
    a = _nfc(answer)
    seen: set[tuple[int, ...]] = set()
    out = []
    for pat in _PAGE_ONLY_PATTERNS:
        for m in pat.finditer(a):
            pgs = _expand_pages(m.group("pgs") or "")
            if not pgs:
                continue
            key = tuple(pgs)
            if key in seen:
                continue
            seen.add(key)
            out.append(pgs)
    return out


# ── Validation ───────────────────────────────────────────────────────


def _source_matches(cited: str, retrieved_source: str) -> bool:
    """Tolerant source matching: substring (after normalization) counts."""
    cited_n = _normalize_source(cited)
    actual_n = _normalize_source(retrieved_source)
    if not cited_n or not actual_n:
        return False
    if cited_n == actual_n:
        return True
    return cited_n in actual_n or actual_n in cited_n


def validate_citations(parsed: list[dict], retrieved_chunks: list[dict]) -> dict:
    """Decide whether each parsed citation is supported by the retrieved set.

    Returns:
      {
        "n_citations": int,
        "n_source_valid": int,
        "n_page_valid": int,
        "source_accuracy": float | None,
        "page_accuracy": float | None,
        "per_citation": [
          {"source", "pages", "raw", "source_exists", "page_matches", "valid"},
          ...
        ],
      }
    """
    by_source: dict[str, list[list[int]]] = {}
    for c in retrieved_chunks:
        s = c.get("source", "")
        pages = _coerce_pages_field(c.get("pages"))
        by_source.setdefault(s, []).append(pages)

    per = []
    for cit in parsed:
        cited_src = cit.get("source", "")
        cited_pages = cit.get("pages", []) or []
        source_exists = False
        page_matches = False
        for actual_src, page_lists in by_source.items():
            if not _source_matches(cited_src, actual_src):
                continue
            source_exists = True
            if not cited_pages:
                page_matches = True
                break
            for pl in page_lists:
                if any(p in cited_pages for p in pl):
                    page_matches = True
                    break
            if page_matches:
                break
        per.append({
            "source": cited_src,
            "pages": cited_pages,
            "raw": cit.get("raw", ""),
            "source_exists": source_exists,
            "page_matches": page_matches,
            "valid": source_exists and page_matches,
        })

    n = len(per)
    n_src = sum(1 for p in per if p["source_exists"])
    n_pg = sum(1 for p in per if p["valid"])
    return {
        "n_citations": n,
        "n_source_valid": n_src,
        "n_page_valid": n_pg,
        "source_accuracy": (n_src / n) if n else None,
        "page_accuracy": (n_pg / n) if n else None,
        "per_citation": per,
    }


def parse_and_validate(answer: str, retrieved_chunks: list[dict]) -> dict:
    """One-call helper used by the eval harness and trace builder."""
    parsed = parse_citations(answer)
    validation = validate_citations(parsed, retrieved_chunks)
    return {"parsed": parsed, "validation": validation}
