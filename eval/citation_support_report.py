"""Cross-arm view of citation claim support, with the resolution sanity check.

The guard this exists for: arm C cites precise pages INSIDE multi-page chunks, and
union resolution is supposed to make that free. If arm C lands materially below
arm A here, that is a bug in evidence resolution, not a finding about arm C — the
SUBSET grade would be getting penalised, which is exactly the failure that made one
of the rejected designs invert the arm ordering.

Also prints the scope of each arm, because arms A/B validate against their own
shown context and arm C against the whole corpus. Those are different constructs
and the means must never be blended.

No LLM calls; reads the backfilled results files.
"""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

EVAL = Path(__file__).resolve().parent

ARMS = {
    "A": ("hybrid RAG", "results_hard.json"),
    "B": ("whole corpus", "results_hard_B_corpus.json"),
    "C": ("agentic files", "results_hard_C_corpus.json"),
}


def _mean(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return statistics.mean(xs) if xs else None


def _f(v, nd=3):
    return "n/a" if v is None else f"{v:.{nd}f}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--suffix", default="", help="e.g. _jr1 to read the variant files")
    args = ap.parse_args()

    rows = []
    for arm, (name, fname) in ARMS.items():
        path = EVAL / (fname.replace(".json", f"{args.suffix}.json") if args.suffix else fname)
        if not path.exists():
            print(f"missing {path.name}; skipping arm {arm}")
            continue
        env = json.loads(path.read_text(encoding="utf-8"))
        res = env.get("results", [])
        cs = [(r.get("citation_claim_support") or {}) for r in res]
        if not any(c.get("claim_support_avg") is not None for c in cs):
            print(f"arm {arm}: not backfilled yet ({path.name})")
            continue

        grades: dict[str, int] = {}
        grade_scores: dict[str, list[float]] = {}
        for c in cs:
            for pc in c.get("per_citation") or []:
                g = pc.get("resolution") or "?"
                grades[g] = grades.get(g, 0) + 1
                if isinstance(pc.get("score"), (int, float)):
                    grade_scores.setdefault(g, []).append(pc["score"])

        bytype: dict[str, list[float]] = {}
        for r in res:
            v = (r.get("citation_claim_support") or {}).get("claim_support_avg")
            if isinstance(v, (int, float)):
                bytype.setdefault(r.get("question_type", "?"), []).append(v)

        # An UNRESOLVED_SOURCE citation scores 0.0, which is right for a fabricated
        # source but wrong when the name is real and merely failed to match. Report
        # both views so a source-matching defect cannot masquerade as an arm result.
        occ_all, occ_res = [], []
        for c in cs:
            for o in c.get("per_occurrence") or []:
                if not o:
                    continue
                v = o.get("support_fraction")
                if isinstance(v, (int, float)):
                    occ_all.append(v)
                    if o.get("reason") != "unresolved":
                        occ_res.append(v)

        rows.append({
            "arm": arm, "name": name,
            "scope": env.get("citation_support_scope"),
            "runs": env.get("citation_support_runs"),
            "support_resolved": _mean(occ_res),
            "n_unres_occ": len(occ_all) - len(occ_res),
            "page_acc": _mean([(r.get("citation_validation") or {}).get("page_accuracy")
                               for r in res]),
            "support": _mean([c.get("claim_support_avg") for c in cs]),
            "occ": sum(c.get("n_occurrences", 0) for c in cs),
            "scored": sum(c.get("n_scored", 0) for c in cs),
            "unres": sum(c.get("n_unresolved", 0) for c in cs),
            "exact": sum(c.get("n_quote_exact", 0) for c in cs),
            "fuzzy": sum(c.get("n_quote_fuzzy", 0) for c in cs),
            "rej": sum(c.get("n_quote_rejected", 0) for c in cs),
            "calls": sum(c.get("llm_calls", 0) for c in cs),
            "grades": grades,
            "grade_means": {g: statistics.mean(v) for g, v in grade_scores.items()},
            "bytype": {k: statistics.mean(v) for k, v in bytype.items()},
        })

    if not rows:
        return 1

    print("| arm | scope | page_acc | claim_support | resolved-only | unresolved occ | calls |")
    print("|---|---|---|---|---|---|---|")
    for r in rows:
        print(f"| {r['arm']} — {r['name']} | {r['scope']} | {_f(r['page_acc'])} | "
              f"**{_f(r['support'])}** | {_f(r['support_resolved'])} | {r['n_unres_occ']} | "
              f"{r['calls']} |")

    print("\nResolution grades (SUBSET = a precise page inside a multi-page chunk; "
          "it must NEVER be penalised):")
    for r in rows:
        g = ", ".join(f"{k} {v}" for k, v in sorted(r["grades"].items(), key=lambda kv: -kv[1]))
        print(f"  {r['arm']}: {g}")

    print("\nMean score BY grade — the direct test of whether precise citations are punished:")
    for r in rows:
        gm = ", ".join(f"{k} {_f(v)}" for k, v in sorted(r["grade_means"].items()))
        print(f"  {r['arm']}: {gm}")

    print("\nQuote verification (fuzzy = would have been wrongly demoted by a strict "
          "substring check):")
    for r in rows:
        print(f"  {r['arm']}: exact {r['exact']}, fuzzy {r['fuzzy']}, rejected {r['rej']}")

    types = sorted({t for r in rows for t in r["bytype"]})
    print("\nBy question type:")
    print("  " + "arm  " + "  ".join(f"{t[:11]:>11}" for t in types))
    for r in rows:
        print(f"  {r['arm']:<4} " + "  ".join(f"{_f(r['bytype'].get(t)):>11}" for t in types))

    # ── The guard ────────────────────────────────────────────────────
    a = next((r for r in rows if r["arm"] == "A"), None)
    c = next((r for r in rows if r["arm"] == "C"), None)
    print()
    if a and c and a["support_resolved"] is not None and c["support_resolved"] is not None:
        raw = (c["support"] - a["support"]) if None not in (c["support"], a["support"]) else None
        delta = c["support_resolved"] - a["support_resolved"]
        print(f"GUARD  arm C - arm A  = {raw:+.3f} raw, {delta:+.3f} excluding unresolved-source")
        # The hypothesis under test is specifically "is SUBSET being penalised".
        sub = [(r["arm"], r["grades"].get("SUBSET", 0)) for r in rows]
        print(f"       SUBSET counts: " + ", ".join(f"{k} {v}" for k, v in sub))
        if delta < -0.05:
            print("  ** STOP. Arm C is materially below arm A even after excluding")
            print("  ** unresolved sources. Arm C cites precise pages inside multi-page")
            print("  ** chunks and union resolution is supposed to make that free, so")
            print("  ** treat this as a RESOLUTION BUG, not a finding.")
        else:
            print("  OK — no inversion attributable to page resolution. Compare the SUBSET")
            print("  mean against EXACT below: if SUBSET >= EXACT, precise citations are not")
            print("  being penalised and any residual gap is not a union-resolution defect.")
    if len({r["scope"] for r in rows}) > 1:
        print("\nNOTE: arms differ in support_scope. Those are different constructs "
              "(own context vs whole corpus). Do not average or rank across them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
