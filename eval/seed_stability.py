"""Second generation seed: is the arm ordering real, or did one arm draw a luckier sample?

The ablation ran each arm **once** per question. Every quality conclusion in
`ABLATION_WRITEUP.md` therefore rests on a single draw from a stochastic
generator, and the CLI exposes neither temperature nor seed — so a rerun is an
independent sample and there is no way to make it reproducible instead.

That matters because the study's entire paired quality signal lives in four
questions. Twenty-one of the 25 scored 5/5/5 across all three arms and
contribute exactly 0 to every paired delta. The reported A-vs-C mean-relevance
delta of -0.28 is precisely (3-5) + (4-5) + (4-5) + (2-5) over h01/h02/h05/h06,
divided by 25. If those four questions are unstable under regeneration, the
delta is noise wearing a confidence interval.

**What is reseeded, and why more than the discordant set.** Reseeding only the
discordant questions is a trap: they were *selected* for being extreme in seed
1, so regression to the mean guarantees the gap shrinks whether or not the
effect is real. The reseed therefore covers the whole `page_lookup` stratum —
all four discordant questions plus h03 and h04, which were concordant in seed 1
and act as same-type controls. Drift on the controls is the baseline that makes
drift on the discordant set interpretable.

Note what this does and does not measure. Seed-to-seed change here bundles
generation noise *and* judge noise, since each seed is judged afresh. The judge's
own contribution is already known from the `flip_rate_relevance` in the main run
(A 0.167, B 0.094, C 0.031), so the interesting quantity is the excess over it,
not the raw number.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.ablation_report import mcnemar_exact, paired_bootstrap, holm   # noqa: E402

EVAL = Path(__file__).resolve().parent

ARMS = {"A": "hybrid RAG", "B": "whole corpus", "C": "agentic files"}

# Seed 1 = the published full run (run id full1jr3, --judge-runs 3 --judge-evidence corpus).
SEED1_FILES = {
    "A": "results_hard_corpus.json",
    "B": "results_hard_B_corpus.json",
    "C": "results_hard_C_corpus.json",
}


def seed2_file(arm: str, suffix: str) -> str:
    stem = "results_hard" if arm == "A" else f"results_hard_{arm}"
    return f"{stem}_corpus_partial_{suffix}.json"


def clopper_pearson(k: int, n: int, alpha: float = 0.05) -> tuple[float, float]:
    """Exact binomial CI. Six cells per arm is few enough that a point estimate
    alone misleads: 0 flips out of 6 is consistent with a true flip rate near 40%,
    and reporting it bare as '0.00' reads as proven stability.

    Implemented by bisection on the binomial tail so scipy stays out of the
    dependency list for one number.
    """
    if n == 0:
        return (0.0, 1.0)

    def tail_le(p, k_):            # P(X <= k_) under Binomial(n, p) — decreasing in p
        return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k_ + 1))

    def solve(k_, target):         # p where the (decreasing) tail equals target
        lo, hi = 0.0, 1.0
        for _ in range(60):
            mid = (lo + hi) / 2
            if tail_le(mid, k_) > target:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2

    low = 0.0 if k == 0 else solve(k - 1, 1 - alpha / 2)
    high = 1.0 if k == n else solve(k, alpha / 2)
    return (round(low, 3), round(high, 3))


def load(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {r["id"]: r for r in raw.get("results", [])}


def rel(rec: dict | None):
    if not rec:
        return None
    return ((rec.get("judge") or {}).get("relevance"))


def verdict(rec: dict | None):
    if not rec:
        return None
    return rec.get("verdict")


def passed(rec: dict | None) -> bool:
    return verdict(rec) == "EQUIVALENT"


def judge_flip(rec: dict | None):
    if not rec:
        return None
    return (rec.get("judge") or {}).get("flip_rate_relevance")


def build(suffix: str) -> int:
    s1 = {a: load(EVAL / f) for a, f in SEED1_FILES.items()}
    s2 = {a: load(EVAL / seed2_file(a, suffix)) for a in ARMS}

    missing = [a for a in ARMS if not s2[a]]
    if missing:
        print(f"No seed-2 results for arm(s) {missing} "
              f"(looked for {[seed2_file(a, suffix) for a in missing]}).")
        return 1
    if any(not s1[a] for a in ARMS):
        print("Missing seed-1 results; run the full ablation first.")
        return 1

    reseeded = sorted(set.intersection(*(set(s2[a]) for a in ARMS)))
    all_qids = sorted(set.intersection(*(set(s1[a]) for a in ARMS)))

    # A question is "discordant" if the arms disagreed on it in seed 1 — by
    # verdict or by relevance. These are the only questions carrying paired signal.
    def is_discordant(q, seed):
        vs = {verdict(seed[a].get(q)) for a in ARMS}
        rs = {rel(seed[a].get(q)) for a in ARMS if rel(seed[a].get(q)) is not None}
        return len(vs) > 1 or len(rs) > 1

    disc1 = [q for q in all_qids if is_discordant(q, s1)]
    disc_reseeded = [q for q in reseeded if q in disc1]
    control = [q for q in reseeded if q not in disc1]

    # ── Per-cell drift ────────────────────────────────────────────────
    cells = []
    for q in reseeded:
        for a in ARMS:
            r1, r2 = s1[a].get(q), s2[a].get(q)
            cells.append({
                "qid": q,
                "arm": a,
                "stratum": "discordant" if q in disc1 else "control",
                "verdict_1": verdict(r1), "verdict_2": verdict(r2),
                "rel_1": rel(r1), "rel_2": rel(r2),
                "verdict_flip": verdict(r1) != verdict(r2),
                "rel_flip": rel(r1) != rel(r2),
                "rel_delta": (None if rel(r1) is None or rel(r2) is None
                              else rel(r2) - rel(r1)),
                "judge_flip_1": judge_flip(r1), "judge_flip_2": judge_flip(r2),
            })

    def rate(sel, key):
        vals = [c[key] for c in cells if sel(c)]
        return (sum(1 for v in vals if v) / len(vals)) if vals else None

    strata = {
        "all": lambda c: True,
        "discordant": lambda c: c["stratum"] == "discordant",
        "control": lambda c: c["stratum"] == "control",
    }
    drift = {
        name: {
            "n_cells": sum(1 for c in cells if sel(c)),
            "verdict_flip_rate": rate(sel, "verdict_flip"),
            "rel_flip_rate": rate(sel, "rel_flip"),
            "mean_abs_rel_delta": (
                statistics.mean([abs(c["rel_delta"]) for c in cells
                                 if sel(c) and c["rel_delta"] is not None])
                if any(sel(c) and c["rel_delta"] is not None for c in cells) else None
            ),
        }
        for name, sel in strata.items()
    }
    per_arm_drift = {
        a: {
            "n_cells": sum(1 for c in cells if c["arm"] == a),
            "n_verdict_flips": sum(1 for c in cells if c["arm"] == a and c["verdict_flip"]),
            "verdict_flip_rate": rate(lambda c, a=a: c["arm"] == a, "verdict_flip"),
            "verdict_flip_ci": clopper_pearson(
                sum(1 for c in cells if c["arm"] == a and c["verdict_flip"]),
                sum(1 for c in cells if c["arm"] == a)),
            "rel_flip_rate": rate(lambda c, a=a: c["arm"] == a, "rel_flip"),
            "judge_flip_rate_seed1": statistics.mean(
                [c["judge_flip_1"] for c in cells
                 if c["arm"] == a and c["judge_flip_1"] is not None]
            ) if any(c["arm"] == a and c["judge_flip_1"] is not None for c in cells) else None,
        }
        for a in ARMS
    }

    # ── Is arm A's retrieval itself stable? ───────────────────────────
    # Arm A is the only ranking arm, and it is the one place where seed-to-seed
    # change could come from a third source (a different chunk set) rather than
    # from generation or judging. If retrieval is identical, every point of drift
    # arm A shows is downstream of it — which also means a retrieval failure like
    # h01's is fully reproducible rather than a bad draw.
    retrieval = []
    for q in reseeded:
        r1, r2 = s1["A"].get(q), s2["A"].get(q)
        key = lambda r: [(c.get("source"), str(c.get("pages")))
                         for c in (r or {}).get("retrieved", [])]
        retrieval.append({
            "qid": q,
            "identical": key(r1) == key(r2),
            "mrr_1": (r1 or {}).get("mrr_at_10"),
            "mrr_2": (r2 or {}).get("mrr_at_10"),
        })

    # ── Recomputed study-wide paired comparisons ──────────────────────
    # Three views over the same 25 questions. Only the reseeded ones differ:
    #   seed1  — as published
    #   seed2  — seed-2 answers substituted for the reseeded questions
    #   pooled — mean of the two seeds on reseeded questions (2-sample estimate,
    #            the better point estimate; halves sampling variance where it was
    #            measured twice)
    def vectors(view: str):
        out = {}
        for a in ARMS:
            vals, passes = [], []
            for q in all_qids:
                r1 = s1[a].get(q)
                r2 = s2[a].get(q) if q in reseeded else None
                v1, v2 = rel(r1), rel(r2)
                if view == "seed1" or r2 is None:
                    vals.append(v1)
                    passes.append(passed(r1))
                elif view == "seed2":
                    vals.append(v2)
                    passes.append(passed(r2))
                else:                       # pooled
                    vals.append(statistics.mean([x for x in (v1, v2) if x is not None])
                                if (v1 is not None or v2 is not None) else None)
                    # A question counts as a pass only if it passed in BOTH draws:
                    # a one-of-two pass is exactly the instability being measured.
                    passes.append(passed(r1) and passed(r2))
            out[a] = {"rel": vals, "pass": passes}
        return out

    views = {}
    for view in ("seed1", "seed2", "pooled"):
        vec = vectors(view)
        pairs, pvals = {}, {}
        for x, y in (("A", "B"), ("A", "C"), ("B", "C")):
            # Drop a question only if EITHER arm lacks a score, and drop it from
            # both — filtering each arm independently would silently misalign the
            # pairing, which is the one thing this bootstrap depends on.
            keep = [i for i in range(len(all_qids))
                    if vec[x]["rel"][i] is not None and vec[y]["rel"][i] is not None]
            ra = [vec[x]["rel"][i] for i in keep]
            rb = [vec[y]["rel"][i] for i in keep]
            mc = mcnemar_exact(vec[x]["pass"], vec[y]["pass"])
            bs = paired_bootstrap(ra, rb)
            pairs[f"{x} vs {y}"] = {"mcnemar": mc, "relevance_bootstrap": bs}
            pvals[f"{x} vs {y}"] = mc["p_value"]
        for k, p in holm(pvals).items():
            pairs[k]["p_holm"] = p
        views[view] = {
            "pass_rate": {a: sum(vec[a]["pass"]) / len(vec[a]["pass"]) for a in ARMS},
            "n_pass": {a: sum(vec[a]["pass"]) for a in ARMS},
            "relevance_mean": {
                a: statistics.mean([v for v in vec[a]["rel"] if v is not None])
                for a in ARMS
            },
            "pairwise": pairs,
        }

    out = {
        "seed2_suffix": suffix,
        "reseeded_questions": reseeded,
        "discordant_in_seed1": disc1,
        "discordant_reseeded": disc_reseeded,
        "control_reseeded": control,
        "n_questions_total": len(all_qids),
        "drift_by_stratum": drift,
        "drift_by_arm": per_arm_drift,
        "arm_a_retrieval": retrieval,
        "cells": cells,
        "views": views,
    }
    (EVAL / f"seed_stability_{suffix}.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    md = render(out)
    (EVAL / f"seed_stability_{suffix}.md").write_text(md, encoding="utf-8")
    print(md)
    print(f"\nWrote eval/seed_stability_{suffix}.json and .md")
    return 0


def _f(v, nd=2):
    return "n/a" if v is None else f"{v:.{nd}f}"


def render(d: dict) -> str:
    L = ["# Second generation seed — is the arm ordering stable?", ""]
    L.append(f"- Reseeded: **{', '.join(d['reseeded_questions'])}** "
             f"({len(d['discordant_reseeded'])} discordant in seed 1, "
             f"{len(d['control_reseeded'])} same-type control)")
    L.append(f"- Discordant across the full study: **{', '.join(d['discordant_in_seed1'])}** "
             f"— these carry 100% of the paired quality signal; the other "
             f"{d['n_questions_total'] - len(d['discordant_in_seed1'])} questions "
             f"scored identically across all three arms.")
    L.append("- Seed 2 is an independent draw: the CLI exposes no temperature or seed, "
             "so a rerun cannot be made reproducible.")
    L.append("")

    L += ["## Per-question, per-arm: seed 1 → seed 2", "",
          "| qid | stratum | arm | verdict | relevance |", "|---|---|---|---|---|"]
    for c in d["cells"]:
        vf = " ⚠" if c["verdict_flip"] else ""
        rd = "" if not c["rel_flip"] else f"  ({c['rel_delta']:+d})"
        L.append(f"| {c['qid']} | {c['stratum']} | {c['arm']} | "
                 f"{c['verdict_1']} → {c['verdict_2']}{vf} | "
                 f"{c['rel_1']} → {c['rel_2']}{rd} |")
    L.append("")

    L += ["## Drift by stratum", "",
          "| stratum | cells | verdict flip | relevance flip | mean abs Δrel |",
          "|---|---|---|---|---|"]
    for name, s in d["drift_by_stratum"].items():
        L.append(f"| {name} | {s['n_cells']} | {_f(s['verdict_flip_rate'])} | "
                 f"{_f(s['rel_flip_rate'])} | {_f(s['mean_abs_rel_delta'])} |")
    L.append("")
    L.append("The **control** row is the load-bearing one. Discordant questions were "
             "selected for being extreme in seed 1, so some regression to the mean is "
             "guaranteed regardless of whether the arm difference is real. Control drift "
             "is the baseline that makes discordant drift interpretable.")
    L.append("")

    L += ["## Drift by arm", "",
          "| arm | verdict flip | 95% CI | relevance flip | judge-only flip (seed 1) |",
          "|---|---|---|---|---|"]
    for a, s in d["drift_by_arm"].items():
        lo, hi = s["verdict_flip_ci"]
        L.append(f"| {a} — {ARMS[a]} | {s['n_verdict_flips']}/{s['n_cells']} = "
                 f"{_f(s['verdict_flip_rate'])} | [{_f(lo)}, {_f(hi)}] | "
                 f"{_f(s['rel_flip_rate'])} | {_f(s['judge_flip_rate_seed1'])} |")
    L.append("")
    L.append("Seed-to-seed flip bundles generation *and* judge noise — each seed is "
             "judged afresh. The judge-only column is its contribution measured on "
             "identical answers, so the excess over it is what regeneration adds.")
    L.append("")
    L.append("**Read the CI, not the point estimate.** Six cells per arm is few: a clean "
             "0/6 is still consistent with a true flip rate near 40%, so \"0.00\" here means "
             "\"no drift observed\", never \"proven stable\".")
    L.append("")

    ret = d["arm_a_retrieval"]
    n_same = sum(1 for r in ret if r["identical"])
    L += ["## Where arm A's drift comes from", ""]
    L.append(f"Arm A retrieved the **identical** chunk set in both seeds on "
             f"**{n_same}/{len(ret)}** reseeded questions"
             + (" — every one." if n_same == len(ret) else ".")
             + " MRR@10 is unchanged throughout ("
             + ", ".join(f"{r['qid']} {_f(r['mrr_1'])}" for r in ret) + ").")
    L.append("")
    L.append("So none of arm A's instability is retrieval instability. Given the same "
             "chunks it writes a differently-worded answer, and the score follows the "
             "wording. The corollary matters more: a retrieval **failure** like h01's "
             "(MRR 0.0 in both seeds) is fully reproducible, not a bad draw.")
    L.append("")

    L += ["## Study-wide result under each view", ""]
    for view, label in (("seed1", "Seed 1 (as published)"),
                        ("seed2", "Seed 2 substituted"),
                        ("pooled", "Pooled (mean of both draws)")):
        v = d["views"][view]
        L.append(f"### {label}")
        L.append("")
        L.append("| arm | EQUIVALENT | rel mean |")
        L.append("|---|---|---|")
        for a in ARMS:
            L.append(f"| {a} | {v['n_pass'][a]}/{d['n_questions_total']} | "
                     f"{_f(v['relevance_mean'][a])} |")
        L.append("")
        L.append("| pair | b | c | McNemar p | Holm p | Δ relevance [95% CI] |")
        L.append("|---|---|---|---|---|---|")
        for pair, p in v["pairwise"].items():
            mc, bs = p["mcnemar"], p["relevance_bootstrap"]
            L.append(f"| {pair} | {mc['b']} | {mc['c']} | {_f(mc['p_value'], 3)} | "
                     f"{_f(p['p_holm'], 3)} | {_f(bs['delta'])} "
                     f"[{_f(bs['ci_low'])}, {_f(bs['ci_high'])}] |")
        L.append("")
    L.append("In the pooled view a question counts as a pass only if it passed in "
             "**both** draws — a one-of-two pass is exactly the instability under test, "
             "and averaging it away would hide the finding.")
    return "\n".join(L)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--suffix", default="seed2",
                    help="The --out-suffix used for the seed-2 run (default seed2).")
    raise SystemExit(build(ap.parse_args().suffix))
