"""Compare the ablation arms with paired statistics. No LLM calls.

Reads the per-arm results files and emits ``eval/ablation_results.json`` plus a
human-readable ``eval/ablation_report.md``.

Statistical stance
==================
n=25 paired questions is small, and saying so precisely matters more than any
point estimate this produces.

* **Paired, not unpaired.** Every arm answers the same 25 questions, so the
  comparison conditions on question difficulty. Bootstrap resamples *question
  indices* and applies the same indices to all arms.
* **Exact McNemar**, not chi-square: at this n the chi-square approximation is
  invalid. Only discordant pairs carry information.
* **Holm correction** across the three pairwise comparisons. No omnibus test —
  Friedman at n=25 over 3 arms is underpowered and routinely misread.
* **Minimum detectable effect is simulated, not asserted.** The report states
  the smallest pass-rate gap this design could detect at 80% power, so a null
  result cannot be misread as evidence of equivalence.
* Per-type breakdowns are descriptive only: 4-6 questions per type has no power.

Usage
=====
    python eval/ablation_report.py
    python eval/ablation_report.py --suffix _corpus       # judge-evidence mode
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

EVAL = ROOT / "eval"
SEED = 20260725
N_BOOT = 10000

ARMS = [
    ("A", "hybrid RAG", "results_hard{suffix}.json"),
    ("B", "whole corpus", "results_hard_B{suffix}.json"),
    ("C", "agentic files", "results_hard_C{suffix}.json"),
]


# ── Loading ──────────────────────────────────────────────────────────


def load_arm(pattern: str, suffix: str) -> dict | None:
    path = EVAL / pattern.format(suffix=suffix)
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload["results"] if isinstance(payload, dict) else payload
    meta = {k: v for k, v in payload.items() if k != "results"} if isinstance(payload, dict) else {}
    meta["_path"] = str(path)
    return {"rows": {r["id"]: r for r in rows}, "meta": meta}


# ── Metrics ──────────────────────────────────────────────────────────


def _num(vals):
    vals = [v for v in vals if isinstance(v, (int, float))]
    return vals


def summarize(rows: dict) -> dict:
    rs = list(rows.values())
    n = len(rs)
    crit: dict[str, int] = {}
    for r in rs:
        for e in (r.get("judge") or {}).get("critical_errors") or []:
            if e != "NONE":
                crit[e] = crit.get(e, 0) + 1

    def tel(key):
        return _num([(r.get("telemetry") or {}).get(key) for r in rs])

    walls = []
    for r in rs:
        t = r.get("telemetry") or {}
        walls.append((t.get("retrieval_wall_s") or 0) + (t.get("generation_wall_s") or 0))
    walls = _num(walls)

    ncits = _num([(r.get("citation_validation") or {}).get("n_citations") for r in rs])
    zero_cit = sum(1 for v in ncits if v == 0)
    page_acc = _num([(r.get("citation_validation") or {}).get("page_accuracy") for r in rs])

    rel = _num([(r.get("judge") or {}).get("relevance") for r in rs])
    gnd = _num([(r.get("judge") or {}).get("groundedness") for r in rs])

    # Judge noise floor. Only meaningful with >1 judge run: with a single sample
    # the flip rate is 0.0 by construction and carries no information.
    flips = _num([(r.get("judge") or {}).get("flip_rate_relevance") for r in rs
                  if (r.get("judge") or {}).get("n_runs", 0) > 1])
    multi_run = [r for r in rs if (r.get("judge") or {}).get("n_runs", 0) > 1]
    # A judged question whose verdict is None is a judge outage, not an arm
    # failure — it must not be counted as a quality miss.
    outages = [r["id"] for r in rs
               if (r.get("judge") or {}).get("relevance") is None
               and r.get("verdict") == "ERROR" and r.get("actual_answer")]
    in_tok = tel("total_input_tokens")
    out_tok = tel("output_tokens")
    cost = tel("cost_usd")
    n_eq = sum(1 for r in rs if r.get("verdict") == "EQUIVALENT")

    return {
        "n": n,
        "n_equivalent": n_eq,
        "equivalent_rate": n_eq / n if n else None,
        "n_partial": sum(1 for r in rs if r.get("verdict") == "PARTIAL"),
        "n_different": sum(1 for r in rs if r.get("verdict") == "DIFFERENT"),
        "n_error": sum(1 for r in rs if r.get("verdict") == "ERROR"),
        "relevance_mean": statistics.mean(rel) if rel else None,
        "relevance_median": statistics.median(rel) if rel else None,
        "groundedness_median": statistics.median(gnd) if gnd else None,
        "citation_page_accuracy_mean": statistics.mean(page_acc) if page_acc else None,
        "median_n_citations": statistics.median(ncits) if ncits else None,
        "pct_zero_citation": (zero_cit / len(ncits) * 100) if ncits else None,
        "critical_errors": crit,
        "flip_rate_relevance_mean": statistics.mean(flips) if flips else None,
        "n_multi_run_judged": len(multi_run),
        "judge_outages": outages,
        "n_judge_outages": len(outages),
        "wall_s_per_q_mean": statistics.mean(walls) if walls else None,
        "wall_s_per_q_p90": (sorted(walls)[int(0.9 * (len(walls) - 1))] if walls else None),
        "input_tokens_per_q_mean": statistics.mean(in_tok) if in_tok else None,
        "output_tokens_per_q_mean": statistics.mean(out_tok) if out_tok else None,
        "cost_usd_total": sum(cost) if cost else None,
        "cost_usd_per_correct": (sum(cost) / n_eq) if cost and n_eq else None,
    }


# ── Paired statistics ────────────────────────────────────────────────


def mcnemar_exact(a_pass: list[bool], b_pass: list[bool]) -> dict:
    """Exact binomial McNemar. Only discordant pairs are informative."""
    b = sum(1 for x, y in zip(a_pass, b_pass) if x and not y)
    c = sum(1 for x, y in zip(a_pass, b_pass) if y and not x)
    n_disc = b + c
    if n_disc == 0:
        return {"b": 0, "c": 0, "n_discordant": 0, "p_value": 1.0}
    k = min(b, c)
    tail = sum(math.comb(n_disc, i) for i in range(k + 1)) / (2 ** n_disc)
    return {"b": b, "c": c, "n_discordant": n_disc, "p_value": min(1.0, 2 * tail)}


def paired_bootstrap(vals_a: list[float], vals_b: list[float], n_boot=N_BOOT, seed=SEED) -> dict:
    """CI for mean(a) - mean(b), resampling QUESTION INDICES applied to both arms.

    Preserving the pairing is the entire point: it cancels per-question difficulty,
    which at n=25 dominates the between-arm signal.
    """
    rng = random.Random(seed)
    n = len(vals_a)
    if n == 0:
        return {"delta": None, "ci_low": None, "ci_high": None}
    diffs = []
    for _ in range(n_boot):
        idx = [rng.randrange(n) for _ in range(n)]
        diffs.append(statistics.mean([vals_a[i] for i in idx])
                     - statistics.mean([vals_b[i] for i in idx]))
    diffs.sort()
    return {
        "delta": statistics.mean(vals_a) - statistics.mean(vals_b),
        "ci_low": diffs[int(0.025 * n_boot)],
        "ci_high": diffs[int(0.975 * n_boot)],
    }


def holm(pvals: dict[str, float]) -> dict[str, float]:
    ordered = sorted(pvals.items(), key=lambda kv: kv[1])
    m = len(ordered)
    out, prev = {}, 0.0
    for i, (k, p) in enumerate(ordered):
        adj = min(1.0, max(prev, (m - i) * p))
        out[k] = adj
        prev = adj
    return out


def minimum_detectable_effect(n=25, alpha=0.05, power=0.80, disc_rate=0.30,
                              seed=SEED, n_sim=4000) -> dict:
    """Smallest true pass-rate gap this design detects at the stated power.

    Simulated rather than asserted, so the report can say plainly which effects
    the study is capable of ruling in — and therefore which null results mean
    "underpowered", not "equivalent".
    """
    rng = random.Random(seed)
    for delta in [d / 100 for d in range(2, 61, 2)]:
        hits = 0
        for _ in range(n_sim):
            b = c = 0
            for _ in range(n):
                if rng.random() < disc_rate:
                    # Among discordant pairs, split implied by the true delta.
                    p_b = 0.5 + (delta / (2 * disc_rate))
                    if rng.random() < min(1.0, max(0.0, p_b)):
                        b += 1
                    else:
                        c += 1
            if mcnemar_exact([True] * b + [False] * c,
                             [False] * b + [True] * c)["p_value"] < alpha:
                hits += 1
        if hits / n_sim >= power:
            return {"mde_pass_rate_gap": delta, "assumed_discordance": disc_rate,
                    "n": n, "alpha": alpha, "power": power}
    return {"mde_pass_rate_gap": None, "assumed_discordance": disc_rate,
            "n": n, "alpha": alpha, "power": power}


# ── Report ───────────────────────────────────────────────────────────


def build(suffix: str) -> int:
    arms, missing = {}, []
    for label, name, pattern in ARMS:
        got = load_arm(pattern, suffix)
        if got is None:
            missing.append(pattern.format(suffix=suffix))
        else:
            arms[label] = {"name": name, **got}
    if missing:
        print("Missing results file(s):")
        for m in missing:
            print(f"  {m}")
        print("\nRun each arm first, e.g.:")
        print("  python eval/run.py --hard --arm A --judge-evidence corpus --run-id full1")
        return 1

    common = sorted(set.intersection(*[set(a["rows"]) for a in arms.values()]))
    if not common:
        print("No question ids common to all arms.")
        return 1

    summaries = {k: summarize({q: a["rows"][q] for q in common}) for k, a in arms.items()}

    # Pairwise paired tests on the common question set.
    pair_stats, raw_p = {}, {}
    keys = list(arms)
    for i, x in enumerate(keys):
        for y in keys[i + 1:]:
            xp = [arms[x]["rows"][q]["verdict"] == "EQUIVALENT" for q in common]
            yp = [arms[y]["rows"][q]["verdict"] == "EQUIVALENT" for q in common]
            mc = mcnemar_exact(xp, yp)
            xr = [(arms[x]["rows"][q].get("judge") or {}).get("relevance") or 0 for q in common]
            yr = [(arms[y]["rows"][q].get("judge") or {}).get("relevance") or 0 for q in common]
            pair = f"{x} vs {y}"
            pair_stats[pair] = {
                "mcnemar": mc,
                "pass_rate_delta": (sum(xp) - sum(yp)) / len(common),
                "relevance_bootstrap": paired_bootstrap(xr, yr),
            }
            raw_p[pair] = mc["p_value"]
    for pair, adj in holm(raw_p).items():
        pair_stats[pair]["p_holm"] = adj

    mde = minimum_detectable_effect(n=len(common))

    out = {
        "n_questions": len(common),
        "question_ids": common,
        "judge_evidence": arms["A"]["meta"].get("judge_evidence"),
        "judge_runs": arms["A"]["meta"].get("judge_runs"),
        "arms": {k: {"name": a["name"], "meta": a["meta"], "summary": summaries[k]}
                 for k, a in arms.items()},
        "pairwise": pair_stats,
        "minimum_detectable_effect": mde,
        "bootstrap": {"n_resamples": N_BOOT, "seed": SEED, "unit": "question index (paired)"},
    }
    (EVAL / f"ablation_results{suffix}.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    # ── Markdown ────────────────────────────────────────────────
    L = []
    L.append("# Ablation: hybrid RAG vs whole-corpus prompting vs agentic file search")
    L.append("")
    L.append(f"- Questions: **{len(common)}** (paired across all arms)")
    L.append(f"- Judge evidence: **{out['judge_evidence']}**, judge runs: {out['judge_runs']}")
    L.append(f"- Generation model: `{arms['A']['meta'].get('arm_name', 'opus')}` family, same for every arm")
    L.append("")
    L.append("## Quality")
    L.append("")
    L.append("| arm | EQUIV | rate | rel mean | rel med | gnd med | cite prec | med n_cit | % zero-cit |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for k, a in arms.items():
        s = summaries[k]
        L.append(
            f"| {k} — {a['name']} | {s['n_equivalent']}/{s['n']} | {s['equivalent_rate']:.0%} | "
            f"{_f(s['relevance_mean'])} | {_f(s['relevance_median'],0)} | {_f(s['groundedness_median'],0)} | "
            f"{_f(s['citation_page_accuracy_mean'])} | {_f(s['median_n_citations'],0)} | "
            f"{_f(s['pct_zero_citation'],0)}% |")
    L.append("")
    L.append("## Judge stability")
    L.append("")
    L.append("| arm | LLM-judged Qs | mean flip-rate (relevance) | judge outages |")
    L.append("|---|---|---|---|")
    for k, a in arms.items():
        s = summaries[k]
        fr = (f"{s['flip_rate_relevance_mean']:.3f}"
              if s["flip_rate_relevance_mean"] is not None else "n/a (single run)")
        out_ids = ", ".join(s["judge_outages"]) or "none"
        L.append(f"| {k} — {a['name']} | {s['n_multi_run_judged']} | {fr} | {out_ids} |")
    L.append("")
    L.append("The flip rate is the judge's own noise floor: the share of adjacent "
             "run pairs whose relevance score disagreed. **No arm gap smaller than "
             "this should be interpreted.** A judge outage is a question where the "
             "judge returned nothing despite the arm producing an answer — it is a "
             "harness failure, not a quality miss, and must not be scored as one.")
    L.append("")
    L.append("## Cost and latency")
    L.append("")
    L.append("| arm | wall s/q (mean) | wall s/q (p90) | input tok/q | output tok/q | $ total | $ per correct |")
    L.append("|---|---|---|---|---|---|---|")
    for k, a in arms.items():
        s = summaries[k]
        L.append(
            f"| {k} — {a['name']} | {_f(s['wall_s_per_q_mean'],1)} | {_f(s['wall_s_per_q_p90'],1)} | "
            f"{_i(s['input_tokens_per_q_mean'])} | {_i(s['output_tokens_per_q_mean'])} | "
            f"{_f(s['cost_usd_total'],2)} | {_f(s['cost_usd_per_correct'],3)} |")
    L.append("")
    L.append("Input tokens are `input + cache_read + cache_creation`. The raw "
             "`input_tokens` field alone reads near-zero when a prompt is served "
             "from cache and would under-report by orders of magnitude.")
    L.append("")
    L.append("## Critical errors")
    L.append("")
    L.append("| arm | " + " | ".join(sorted({e for k in arms for e in summaries[k]["critical_errors"]})) + " |")
    all_errs = sorted({e for k in arms for e in summaries[k]["critical_errors"]})
    L.append("|---|" + "---|" * len(all_errs))
    for k in arms:
        L.append(f"| {k} | " + " | ".join(str(summaries[k]["critical_errors"].get(e, 0))
                                          for e in all_errs) + " |")
    L.append("")
    L.append("## Paired comparisons")
    L.append("")
    L.append("| pair | b | c | discordant | McNemar p | Holm p | Δ pass rate | Δ relevance [95% CI] |")
    L.append("|---|---|---|---|---|---|---|---|")
    for pair, st in pair_stats.items():
        mc, bs = st["mcnemar"], st["relevance_bootstrap"]
        ci = (f"{bs['delta']:+.2f} [{bs['ci_low']:+.2f}, {bs['ci_high']:+.2f}]"
              if bs["delta"] is not None else "—")
        L.append(f"| {pair} | {mc['b']} | {mc['c']} | {mc['n_discordant']} | "
                 f"{mc['p_value']:.3f} | {st['p_holm']:.3f} | {st['pass_rate_delta']:+.1%} | {ci} |")
    L.append("")
    L.append("`b` = questions the first arm passed and the second failed; `c` = the reverse. "
             "Only discordant pairs carry information in a paired test.")
    L.append("")
    L.append("## How much could this study detect?")
    L.append("")
    m = mde
    if m["mde_pass_rate_gap"]:
        L.append(f"At n={m['n']}, α={m['alpha']}, {m['power']:.0%} power and an assumed "
                 f"{m['assumed_discordance']:.0%} discordance rate, the smallest pass-rate "
                 f"gap detectable is **{m['mde_pass_rate_gap']:.0%}**.")
    L.append("")
    L.append("> Any observed gap smaller than that is consistent with noise. This design "
             "can rule *in* large effects; it cannot establish equivalence. The cost and "
             "latency columns are measured far more precisely than the quality columns "
             "and are where the defensible conclusions live.")
    L.append("")
    L.append("## Per-question verdicts")
    L.append("")
    L.append("| qid | type | " + " | ".join(arms) + " |")
    L.append("|---|---|" + "---|" * len(arms))
    for q in common:
        t = arms["A"]["rows"][q].get("question_type", "?")
        L.append(f"| {q} | {t} | " + " | ".join(arms[k]["rows"][q]["verdict"] for k in arms) + " |")
    L.append("")

    (EVAL / f"ablation_report{suffix}.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))
    print(f"\nWrote {EVAL / f'ablation_results{suffix}.json'}")
    print(f"Wrote {EVAL / f'ablation_report{suffix}.md'}")
    return 0


def _f(v, nd=2):
    return f"{v:.{nd}f}" if isinstance(v, (int, float)) else "—"


def _i(v):
    return f"{int(v):,}" if isinstance(v, (int, float)) else "—"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--suffix", default="_corpus",
                    help="Results-file suffix (judge-evidence mode). Default _corpus.")
    raise SystemExit(build(ap.parse_args().suffix))
