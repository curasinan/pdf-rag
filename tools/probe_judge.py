"""Plant defects at EVERY judge — rule-based and LLM — and assert they are caught.

Run after ANY judge edit (rubric text or Python logic). Exit 0 = all probes pass.

Why the rule judges are probed here at all: until Aug 2026 this file contained
zero occurrences of ``page_lookup``, ``_judge_numeric`` or ``_judge_negative`` —
the rule judges deciding 15 of the 25 hard questions had never been defect-probed,
which is how ``_judge_page_lookup`` shipped wrong in BOTH directions (an honest
abstention scored the same gate-blocking WRONG_EVIDENCE as a fabrication, while a
right-entity/fabricated-page answer — the one defect a page_lookup question exists
to catch — produced no error at all).

Sections:
  1. Rule judges (free, deterministic, no LLM). Planted answers are REAL stored
     answers where one exists (freeze1 h01, verify2 h01, norerank h04 — all
     TUNING questions; holdout is never read) plus synthetic fabrications.
  2. Vote aggregation (free — ``_judge_once`` is monkeypatched with scripted
     runs). Includes the freeze1 h07 replay: two accusing runs quoting two
     DISJOINT spans must no longer manufacture a majority no single span earned.
  3. LLM judge end-to-end (~7 CLI calls): the original CLEAN / FABRICATED /
     MISCITED plants against h17. Skipped with ``--rules-only``.

Usage:
    python tools/probe_judge.py               # everything
    python tools/probe_judge.py --rules-only  # sections 1-2 only, no LLM calls
"""
import argparse
import io
import json
import re
import sys
import unicodedata

sys.path.insert(0, ".")

import eval.run as R
from eval.run import (
    _judge_llm_aggregated, _judge_negative, _judge_numeric,
    _judge_once, _judge_page_lookup,
)

FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'OK  ' if ok else 'FAIL'} {name}" + (f"  [{detail}]" if detail else ""))
    if not ok:
        FAILURES.append(name)


def load_results(path: str) -> dict:
    d = json.loads(io.open(path, encoding="utf-8").read())
    return {r["id"]: r for r in d["results"]}


def load_questions() -> dict:
    qs = json.loads(io.open("eval/questions_hard.json", encoding="utf-8").read())
    ql = qs if isinstance(qs, list) else qs.get("questions", qs)
    return {q["id"]: q for q in ql}


# ── Section 1: rule judges ───────────────────────────────────────────


def probe_page_lookup(questions: dict) -> None:
    print("\n[1a] _judge_page_lookup — both directions")
    mc_h01 = questions["h01"]["must_contain"]          # ['table turn', 'page 8']

    def run(answer: str, must_contain: list[str]) -> dict:
        return _judge_page_lookup(answer, must_contain, "expected", "question", "evidence")

    # Honest abstention after a retrieval miss (freeze1's REAL h01 answer): the
    # answer asserts nothing wrong — the context genuinely lacks KPI #5 — so the
    # floor is FORMAT_FAIL, a named non-answer, never the accusing WRONG_EVIDENCE
    # a fabrication earns. Byte-identical treatment of the two was the defect.
    honest = load_results("eval/results_hard.json")["h01"]["actual_answer"]
    out = run(honest, mc_h01)
    check("honest abstention -> FORMAT_FAIL, relevance 1",
          out["critical_errors"] == ["FORMAT_FAIL"] and out["relevance"] == 1,
          f"got {out['critical_errors']} rel={out['relevance']}")

    # Confident fabrication, wrong entity AND wrong page: stays WRONG_EVIDENCE.
    fab = ("According to the guide, the fifth KPI is Instagram Follower Count, "
           "discussed on page 4 [5 KPIs Every Clever Café Manager Should Track, pages 4-6].")
    out = run(fab, mc_h01)
    check("fabrication (wrong entity + page) -> WRONG_EVIDENCE, relevance 1",
          out["critical_errors"] == ["WRONG_EVIDENCE"] and out["relevance"] == 1,
          f"got {out['critical_errors']} rel={out['relevance']}")

    # Page-free fabrication: no citation at all must read as a wrong assertion,
    # never as an abstention — FORMAT_FAIL here would launder a fabrication.
    fab_nopage = ("The guide's fifth KPI is Customer Loyalty Percentage, "
                  "the share of customers who return within a month.")
    out = run(fab_nopage, mc_h01)
    check("page-free fabrication -> WRONG_EVIDENCE, never FORMAT_FAIL",
          out["critical_errors"] == ["WRONG_EVIDENCE"],
          f"got {out['critical_errors']}")

    # THE defect this question type exists to catch: right entity, fabricated
    # page. Before the fix this scored 3/3/3 with NO error at all.
    wrong_page = ("KPI #5 is Table Turn Time — how quickly you serve and reseat "
                  "tables. It is defined on page 3 of the guide "
                  "[5 KPIs Every Clever Café Manager Should Track, page 3].")
    out = run(wrong_page, mc_h01)
    check("right entity + fabricated page -> CITATION_WRONG",
          "CITATION_WRONG" in out["critical_errors"] and out["relevance"] < 3,
          f"got {out['critical_errors']} rel={out['relevance']}")

    # Honest PARTIAL (verify2's REAL h01 answer): names table-turn, hedges the
    # page, cites only what it actually looked at. Must stay 3/3/3 with no error.
    partial = load_results("eval/results_hard_verify2.json")["h01"]["actual_answer"]
    out = run(partial, mc_h01)
    check("honest hedged partial -> 3/3/3, no error",
          out["critical_errors"] == ["NONE"] and out["relevance"] == 3,
          f"got {out['critical_errors']} rel={out['relevance']}")

    # norerank h04's REAL answer: confidently presents the WRONG worked example.
    # Its hedge ("I can't pinpoint a single page number") is about page
    # granularity, not about the context lacking the answer — it must KEEP firing
    # WRONG_EVIDENCE. This is the case that forbids a naive hedge-word detector.
    h04_answer = load_results("eval/results_hard_norerank.json")["h04"]["actual_answer"]
    out = run(h04_answer, questions["h04"]["must_contain"])
    check("norerank h04 (confident wrong numbers) -> still WRONG_EVIDENCE",
          out["critical_errors"] == ["WRONG_EVIDENCE"] and out["relevance"] == 1,
          f"got {out['critical_errors']} rel={out['relevance']}")

    # All phrases present -> must delegate to the LLM judge (4-vs-5 hybrid).
    sentinel = {"relevance": 5, "critical_errors": ["NONE"], "sentinel": True}
    orig = R._judge_llm_aggregated
    R._judge_llm_aggregated = lambda *a, **k: sentinel
    try:
        good = ("KPI #5 is Table Turn Time "
                "[5 KPIs Every Clever Café Manager Should Track, pages 7-8].")
        out = run(good, mc_h01)
    finally:
        R._judge_llm_aggregated = orig
    check("all phrases present -> delegates to LLM judge", out is sentinel)


def probe_numeric() -> None:
    print("\n[1b] _judge_numeric — F13 semantics")
    out = _judge_numeric("The COGS percentage is 32.5% [Workbook, pages 1-2].", [32.5])
    check("correct number -> 5, NONE",
          out["relevance"] == 5 and out["critical_errors"] == ["NONE"],
          f"got {out['critical_errors']} rel={out['relevance']}")
    out = _judge_numeric("COGS runs at 45.0% of revenue.", [32.5])
    check("wrong number -> 1, WRONG_EVIDENCE",
          out["relevance"] == 1 and out["critical_errors"] == ["WRONG_EVIDENCE"],
          f"got {out['critical_errors']} rel={out['relevance']}")
    out = _judge_numeric("The context does not state the COGS percentage.", [32.5])
    check("digit-free abstention -> 1, FORMAT_FAIL (not WRONG_EVIDENCE)",
          out["relevance"] == 1 and out["critical_errors"] == ["FORMAT_FAIL"],
          f"got {out['critical_errors']} rel={out['relevance']}")


def probe_negative() -> None:
    print("\n[1c] _judge_negative — F14 semantics")
    out = _judge_negative("No, the materials do not mention cryptocurrency payments.")
    check("proper refusal -> 5, NONE",
          out["relevance"] == 5 and out["critical_errors"] == ["NONE"],
          f"got {out['critical_errors']} rel={out['relevance']}")
    out = _judge_negative(
        "Yes — the corpus recommends accepting Bitcoin for loyalty points.")
    check("failed negative (asserts absent content) -> 1, HALLUCINATION",
          out["relevance"] == 1 and out["critical_errors"] == ["HALLUCINATION"],
          f"got {out['critical_errors']} rel={out['relevance']}")


# ── Section 2: vote aggregation (scripted runs, no LLM) ──────────────


def _scripted(rel: int, errors: list[str], quotes: list[list[str]]) -> dict:
    return {
        "relevance": rel, "groundedness": rel, "citation_accuracy": rel,
        "critical_errors": errors or ["NONE"],
        "critical_error_quotes": quotes,
        "short_rationale": "scripted",
    }


def aggregate(candidate: str, runs: list[dict]) -> dict:
    orig = R._judge_once
    it = iter(runs)
    R._judge_once = lambda *a, **k: next(it, None)
    try:
        return _judge_llm_aggregated("q", "evidence", "expected", candidate,
                                     n_runs=len(runs))
    finally:
        R._judge_once = orig


def probe_aggregation() -> None:
    print("\n[2] _judge_llm_aggregated — span-aware critical-error voting")

    # freeze1 h07 REPLAY, with the two real quotes from the stored per_run rows:
    # run 1 accused the FAQ-formula span, run 2 accused the summary citation —
    # neither span was accused twice, yet label-only counting produced
    # counts['CITATION_WRONG'] == 2 and a gate-blocking majority. A majority must
    # be a majority ON A SPAN.
    rec = load_results("eval/results_hard.json")["h07"]
    cand = rec["actual_answer"]
    q1 = ('but in the FAQ it gives the margin version, "Fixed Costs / Gross Margin %" '
          '[Briefing Doc - Opening and Operating a Profitable Coffee Shop, pages 4-5]')
    q2 = "[Calculating Your Break Even Point, pages 1-3, 4-5]"
    out = aggregate(cand, [
        _scripted(5, ["NONE"], []),
        _scripted(5, ["CITATION_WRONG"], [["CITATION_WRONG", q1]]),
        _scripted(5, ["CITATION_WRONG"], [["CITATION_WRONG", q2]]),
    ])
    check("h07 replay: same label, two DISJOINT spans -> no majority, no error",
          out["critical_errors"] == ["NONE"],
          f"got {out['critical_errors']}")

    # Two runs quoting different WINDOWS of the same defect must still convict —
    # span identity is overlap in the candidate, not string equality.
    cand2 = ("The guide states that the average coffee shop owner loses 27.4 hours "
             "per week to these interruptions, costing $46,800 annually.")
    out = aggregate(cand2, [
        _scripted(2, ["HALLUCINATION"],
                  [["HALLUCINATION", "owner loses 27.4 hours per week"]]),
        _scripted(2, ["HALLUCINATION"],
                  [["HALLUCINATION", "loses 27.4 hours per week to these interruptions"]]),
        _scripted(4, ["NONE"], []),
    ])
    check("overlapping windows of one span -> majority holds, error fires",
          out["critical_errors"] == ["HALLUCINATION"],
          f"got {out['critical_errors']}")

    # Legacy rows carry bare labels with no quotes (fail-open by design):
    # all-wildcard voting must reproduce label-only counting byte-identically.
    out = aggregate(cand2, [
        _scripted(2, ["HALLUCINATION"], []),
        _scripted(2, ["HALLUCINATION"], []),
        _scripted(4, ["NONE"], []),
    ])
    check("legacy bare-label 2-of-3 -> still a majority (wildcard votes)",
          out["critical_errors"] == ["HALLUCINATION"],
          f"got {out['critical_errors']}")

    # A vote whose every quote fails to resolve in the candidate accuses text the
    # answer never contained; it is discarded before any span logic runs.
    out = aggregate(cand2, [
        _scripted(2, ["HALLUCINATION"],
                  [["HALLUCINATION", "the reference answer's own figures"]]),
        _scripted(2, ["HALLUCINATION"],
                  [["HALLUCINATION", "text that appears nowhere in the candidate"]]),
        _scripted(4, ["NONE"], []),
    ])
    check("unfounded quotes -> votes discarded, no error",
          out["critical_errors"] == ["NONE"],
          f"got {out['critical_errors']}")

    # Total judge outage keeps the conservative unscored shape (gate F11 catches
    # relevance None as an outage — it must never look like a scored NONE-at-5).
    out = aggregate(cand2, [None, None, None])
    check("n_runs == 0 -> relevance None, unscored shape retained",
          out["relevance"] is None and out["n_runs"] == 0
          and out["critical_errors"] == ["NONE"],
          f"got rel={out['relevance']} n_runs={out['n_runs']}")


# ── Section 3: LLM judge end-to-end (the original probe) ─────────────


def probe_llm() -> None:
    print("\n[3] LLM judge end-to-end (h17 plants, ~7 CLI calls)")
    rec = load_results("eval/results_hard.json")["h17"]
    question, expected = rec["question"], rec["expected_answer"]

    from vectorstore import get_all_chunks
    chunks = get_all_chunks(project="capstone")

    def pg(p):
        if isinstance(p, (list, tuple)):
            return tuple(int(x) for x in p)
        return tuple(int(x) for x in re.findall(r"\d+", str(p)))

    nfc = lambda s: unicodedata.normalize("NFC", str(s or ""))
    lookup = {(nfc(c["source"]), pg(c["pages"])): c["text"] for c in chunks}
    parts = []
    for c in rec["retrieved"]:
        t = lookup.get((nfc(c["source"]), pg(c["pages"])), "")
        pages = ", ".join(str(x) for x in pg(c["pages"]))
        parts.append(f"[{c['source']}, pages {pages}]\n{t}")
    evidence = "\n\n---\n\n".join(parts)

    CLEAN = rec["actual_answer"]
    FABRICATED = (
        'The Cost of Time refers to owner time lost to customers, vendors and employees '
        '[7 Costs That Sink Coffee Shops, pages 14-17]. The guide states that the average '
        'coffee shop owner loses 27.4 hours per week to these interruptions, costing '
        '$46,800 annually [7 Costs That Sink Coffee Shops, pages 14-17].'
    )
    MISCITED = (
        'The Cost of Time refers to owner time lost to issues with customers, vendors and '
        'employees, which makes owners "inefficient, grumpy, and ineffective at making good '
        'decisions" [How to Increase Your Coffee Shop Profits with Loyalty Programs, pages 11-13].'
    )

    for name, cand, want in [("CLEAN", CLEAN, "NONE"),
                             ("FABRICATED", FABRICATED, "HALLUCINATION"),
                             ("MISCITED", MISCITED, "CITATION_WRONG")]:
        out = _judge_once(question, evidence, expected, cand)
        if out is None:
            check(f"{name} -> {want}", False, "judge failed to parse")
            continue
        errs = out["critical_errors"]
        quotes = out.get("critical_error_quotes") or []
        hit = (want in errs) if want != "NONE" else (errs == ["NONE"])
        check(f"{name} -> {want}", hit, f"got {errs}")
        for lbl, q in quotes:
            inside = R._quote_is_in_candidate(q, cand)
            print(f"        quote[{lbl}] resolves_in_candidate={inside}: {q[:110]!r}")
        if errs != ["NONE"] and not quotes:
            check(f"{name} accusation carries a quote", False,
                  "flagged WITHOUT a quote: schema not honoured, vote would fail open")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rules-only", action="store_true",
                    help="skip the LLM section (no CLI calls)")
    args = ap.parse_args()

    questions = load_questions()
    probe_page_lookup(questions)
    probe_numeric()
    probe_negative()
    probe_aggregation()
    if not args.rules_only:
        probe_llm()
    else:
        print("\n[3] LLM section SKIPPED (--rules-only)")

    print()
    if FAILURES:
        print(f"VERDICT: PROBLEM — {len(FAILURES)} probe(s) failed:")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("VERDICT: every judge still catches its planted defects")
    return 0


if __name__ == "__main__":
    sys.exit(main())
