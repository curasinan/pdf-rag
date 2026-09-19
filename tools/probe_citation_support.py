"""Does the citation-support scorer still CATCH a bad citation?

Same reasoning as ``tools/probe_judge.py``: a prompt edit that raises the score
looks identical to one that blinded the scorer. The only way to tell them apart is
to plant defects and check they are still flagged.

Three planted cases against real corpus chunks:
  1. CLEAN        - a claim cited to the chunk that contains it. Expect ~1.0.
  2. MISCITED     - real content attributed to an unrelated document. Expect low.
  3. FABRICATED_PAGE - a real source, a page that does not exist. Expect UNRESOLVED
                    and zero LLM calls, because it short-circuits before the model.

Run after ANY edit to SUPPORT_SYSTEM / SUPPORT_USER, and bump
CITATION_SUPPORT_PROMPT_VERSION so the cache cannot replay stale verdicts.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from citation_support import (build_idf, llm_adjudicator,          # noqa: E402
                             resolve_evidence, score_citation_support)
from vectorstore import get_all_chunks                             # noqa: E402

PROJECT = "capstone"

CLEAN = (
    'Owners lose time to issues with customers, vendors and employees, and running out '
    'of it makes them "inefficient, grumpy, and ineffective at making good decisions" '
    '[7 Costs That Sink Coffee Shops, pages 14-17].'
)
MISCITED = (
    'Owners lose time to issues with customers, vendors and employees, and running out '
    'of it makes them "inefficient, grumpy, and ineffective at making good decisions" '
    '[How to Increase Your Coffee Shop Profits with Loyalty Programs, pages 11-13].'
)
FABRICATED_PAGE = (
    'Owners lose time to issues with customers, vendors and employees '
    '[7 Costs That Sink Coffee Shops, pages 88-90].'
)


def main() -> int:
    chunks = get_all_chunks(project=PROJECT)
    idf = build_idf(chunks)
    adj = llm_adjudicator()

    # Case 3 must never reach the model.
    _, _, grade = resolve_evidence(
        {"source": "7 Costs That Sink Coffee Shops", "pages": [88, 89, 90]}, chunks)
    print(f"FABRICATED_PAGE  resolution={grade}  "
          f"{'OK' if grade == 'UNRESOLVED_PAGES' else 'MISS (expected UNRESOLVED_PAGES)'}")
    ok = grade == "UNRESOLVED_PAGES"

    for name, answer, want_low in (("CLEAN", CLEAN, False), ("MISCITED", MISCITED, True)):
        r = score_citation_support(answer, chunks, scope="own", runs=1,
                                   adjudicator=adj, idf=idf, cache_dir=None)
        avg = r["claim_support_avg"]
        hit = (avg is not None) and ((avg <= 0.5) if want_low else (avg >= 0.8))
        ok = ok and hit
        print(f"{name:<16} claim_support={avg}  llm_calls={r['llm_calls']}  "
              f"quotes exact/fuzzy/rejected={r['n_quote_exact']}/{r['n_quote_fuzzy']}/"
              f"{r['n_quote_rejected']}  "
              f"{'OK' if hit else ('MISS (expected ' + ('low' if want_low else 'high') + ')')}")
        for pc in r["per_citation"]:
            print(f"                  {pc['raw'][:52]:<52} label={pc['label']} "
                  f"score={pc['score']} res={pc['resolution']}")

    print("\nVERDICT:", "scorer still catches planted miscitations"
          if ok else "PROBLEM — a planted defect was not caught")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
