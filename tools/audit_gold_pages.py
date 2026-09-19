"""Audit every gold page label against the source documents.

Why
===
Three separate label defects have now been found by hand (h14, h04, and h07's
incompleteness), all with the same root cause: **gold page sets are chunk-shaped,
not fact-shaped.** They record which retrieved chunk answered the question for
the hybrid-RAG arm, not which page actually prints the fact. That is invisible to
arm A — whose chunks span several pages, so one overlapping page satisfies
``_is_relevant_chunk`` — and systematically punishes arms that read the whole
corpus and cite the precise page.

This script checks the labels mechanically instead of one at a time. For every
question carrying ``expected_numbers`` or ``must_contain``, it finds which pages
of the named source actually contain those tokens (using ``pdf_parser.extract_pages``,
the same extraction the pipeline ingests) and compares that to the gold set.

Read-only; prints a report and exits non-zero if any label looks wrong.

    python tools/audit_gold_pages.py
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from pdf_parser import extract_pages, SUPPORTED_EXTS      # noqa: E402

SOURCES = ROOT / "sources" / "capstone"
QUESTIONS = ROOT / "eval" / "questions_hard.json"


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s or "")


_page_cache: dict[str, list[dict]] = {}


def pages_for_source(source: str) -> list[dict] | None:
    """Extracted pages for a source stem, or None if the file is missing."""
    key = _nfc(source)
    if key in _page_cache:
        return _page_cache[key]
    match = None
    for p in SOURCES.iterdir():
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS and _nfc(p.stem) == key:
            match = p
            break
    if match is None:
        _page_cache[key] = None
        return None
    _page_cache[key] = extract_pages(str(match))
    return _page_cache[key]


def _number_variants(tok: float) -> list[str]:
    """Textual forms a number may take in a document (1234.5 -> '1234.5', '1,234.5')."""
    out = set()
    for v in (tok, tok / 100.0):
        for s in (f"{v:g}", f"{v:,.0f}" if float(v).is_integer() else f"{v:,}"):
            out.add(s)
    if float(tok).is_integer():
        out.add(f"{int(tok):,}")
        out.add(str(int(tok)))
    return [s for s in out if s]


def find_pages(pages: list[dict], needle: str) -> list[int]:
    n = _nfc(needle).lower()
    return [p["page_num"] for p in pages if n in _nfc(p["text"]).lower()]


def audit() -> int:
    questions = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    problems = []

    for q in questions:
        probes: list[tuple[str, list[str]]] = []
        for num in q.get("expected_numbers") or []:
            probes.append((f"number {num:g}", _number_variants(num)))
        for phrase in q.get("must_contain") or []:
            # Page assertions are about the answer's wording, not document content.
            if re.match(r"^\s*(?:pages?|pp?\.?|pg\.?)\s*[\d\s,\-–—]+$", phrase, re.I):
                continue
            probes.append((f"phrase {phrase!r}", [phrase]))
        if not probes:
            continue

        for entry in q.get("must_cite_sources") or []:
            src = entry["source"]
            gold = set(entry.get("pages") or [])
            if not gold:
                continue
            pages = pages_for_source(src)
            if pages is None:
                problems.append((q["id"], src, "SOURCE FILE NOT FOUND", "", ""))
                continue

            for label, variants in probes:
                found = sorted({p for v in variants for p in find_pages(pages, v)})
                if not found:
                    continue          # token lives in another source, or is derived
                if not (set(found) & gold):
                    problems.append((q["id"], src, f"{label} on pages {found}, "
                                     f"gold {sorted(gold)} — NO OVERLAP", found, gold))
                elif not set(found) <= gold:
                    missing = sorted(set(found) - gold)
                    problems.append((q["id"], src, f"{label} also on pages {missing} "
                                     f"(gold {sorted(gold)})", found, gold))

    print(f"Audited {len(questions)} questions against {SOURCES}\n")
    if not problems:
        print("OK: every checkable gold page set covers where the evidence actually is.")
        return 0

    by_q: dict[str, list] = {}
    for qid, src, msg, *_ in problems:
        by_q.setdefault(qid, []).append((src, msg))
    for qid in sorted(by_q):
        print(f"{qid}:")
        for src, msg in by_q[qid]:
            print(f"    [{src[:44]}] {msg}")
    print(f"\n{len(problems)} label discrepancy(ies) across {len(by_q)} question(s).")
    print("A label that omits a page where the fact genuinely appears penalises any")
    print("arm that cites that page — which is the arms that read the whole corpus.")
    return 1


if __name__ == "__main__":
    raise SystemExit(audit())
