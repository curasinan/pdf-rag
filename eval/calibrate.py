"""Judge calibration harness (Weekend-3 Phase B6).

What this measures
==================
For each calibration anchor in ``eval/calibration.json``, run the new evidence-
only 5-axis judge ``n_runs`` times. Compare the median verdict to the
bootstrapped human label. Compute:

- per-axis accuracy: fraction of items where median is within ±1 of the human
  anchor (loose tolerance because the human anchors themselves were derived
  from prior verdicts; tight equality would punish honest borderline cases)
- per-axis flip-rate: mean of stdev / range across the n_runs values
- per-axis dispersion (stdev across the runs)
- confusion at the relevance≥4 PASS gate (the threshold the eval harness uses
  to convert relevance into the legacy EQUIVALENT verdict)

Outputs
=======
    eval/calibration_results.json   — per-anchor + summary
    eval/calibration_results.md     — human-readable

Acceptance criteria for a usable judge (book Chapter 7):
    - relevance accuracy ≥ 80%
    - groundedness accuracy ≥ 80%
    - mean flip-rate < 10%

If those fail, the eval gate cannot be trusted. Don't tighten any other gate
until calibration passes.

Important caveat
================
The current ``calibration.json`` is bootstrapped from prior eval verdicts (see
``bootstrap_method`` field), not human review. A high disagreement rate here
means EITHER the new judge is mis-scoring OR the bootstrapped anchors were
wrong. The Weekend-3 spec acknowledges this — replacement of bootstrapped
anchors with human-reviewed ones is a follow-up.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Import the harness internals we want to exercise.
sys.path.insert(0, str(ROOT / "eval"))
from run import (                                                # noqa: E402
    _judge_llm_aggregated, _judge_numeric, _judge_negative,
    _judge_page_lookup, _verdict_from_relevance,
)
from pipeline import _format_context                              # noqa: E402
from retrieval import hybrid_search                               # noqa: E402

CAL_PATH = ROOT / "eval" / "calibration.json"
OUT_JSON = ROOT / "eval" / "calibration_results.json"
OUT_MD = ROOT / "eval" / "calibration_results.md"

EVAL_PROJECT = "capstone"
PASS_THRESHOLD = 4   # relevance ≥ this counts as PASS for the gate confusion matrix
ACCURACY_TOLERANCE = 1   # judge median within ±N of human anchor counts as accurate


# ── Helpers ──────────────────────────────────────────────────────────


def _load_calibration() -> tuple[list[dict], dict]:
    """Return (items, header_meta). Tolerates both flat-list and envelope forms."""
    raw = json.loads(CAL_PATH.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return raw, {"schema_version": 0, "n_anchors": len(raw)}
    items = raw.get("items", [])
    header = {k: v for k, v in raw.items() if k != "items"}
    return items, header


def _resolve_evidence(item: dict) -> str:
    """Re-fetch chunks for the calibration item.

    The bootstrap step recorded only ``{source, pages}`` per evidence chunk to
    keep the calibration file small. The new evidence-only judge needs the
    actual chunk text, so we run the original question through hybrid_search
    on the same project. This is consistent with how the eval harness builds
    evidence at runtime, so the judge sees the same shape it would in practice.
    """
    question = item.get("question") or ""
    chunks = hybrid_search(question, top_k=10, project=EVAL_PROJECT)
    return _format_context(chunks)


def _run_one_anchor(item: dict, n_runs: int) -> dict:
    """Run the appropriate judge n_runs times on the anchor's
    (question, evidence, expected, candidate). Return the per-axis runs and
    the median scores.

    For numeric / negative / page_lookup we use the rule-based judges (which
    return a single deterministic dict); ``n_runs`` is irrelevant there but
    we still emit the dict to a uniform shape so the aggregation code is
    type-blind."""
    qtype = item.get("question_type", "qa")
    candidate = item.get("candidate_answer") or ""
    expected = item.get("expected_answer") or ""
    question = item.get("question") or ""

    # Rule-based judges short-circuit
    if qtype == "numeric":
        out = _judge_numeric(candidate, item.get("expected_numbers", []))
        return {
            "rule_based": True,
            "runs": [out],
            "rels": [out["relevance"]] * n_runs,
            "gnds": [out["groundedness"]] * n_runs,
            "cits": [out["citation_accuracy"]] * n_runs,
            "errors": [out["critical_errors"]] * n_runs,
        }
    if qtype == "negative":
        out = _judge_negative(candidate)
        return {
            "rule_based": True,
            "runs": [out],
            "rels": [out["relevance"]] * n_runs,
            "gnds": [out["groundedness"]] * n_runs,
            "cits": [out["citation_accuracy"]] * n_runs,
            "errors": [out["critical_errors"]] * n_runs,
        }

    # Need evidence text for the LLM-judge path. Re-resolve.
    evidence = _resolve_evidence(item)
    rels: list[int] = []
    gnds: list[int] = []
    cits: list[int] = []
    errors: list[list[str]] = []
    runs_raw = []

    if qtype == "page_lookup":
        # Hybrid: substring then LLM if all phrases present. Run n times to
        # measure flip-rate even when the substring path resolves it
        # deterministically (it'll be flat — that's fine, the harness wants
        # to see it explicitly).
        for _ in range(n_runs):
            out = _judge_page_lookup(
                candidate, item.get("must_contain", []),
                expected, question, evidence,
            )
            runs_raw.append(out)
            rels.append(out["relevance"])
            gnds.append(out["groundedness"])
            cits.append(out["citation_accuracy"])
            errors.append(out["critical_errors"])
    else:
        # qa, synthesis: full LLM judge (which is itself a 3-run median internally
        # under DEFAULT_JUDGE_RUNS — that's a separate inner aggregation). We run
        # the outer harness n_runs times to measure inter-aggregation stability.
        for _ in range(n_runs):
            out = _judge_llm_aggregated(question, evidence, expected, candidate)
            runs_raw.append(out)
            rels.append(out.get("relevance") or 0)
            gnds.append(out.get("groundedness") or 0)
            cits.append(out.get("citation_accuracy") or 0)
            errors.append(out.get("critical_errors") or ["NONE"])

    return {
        "rule_based": False,
        "runs": runs_raw,
        "rels": rels, "gnds": gnds, "cits": cits, "errors": errors,
    }


def _stdev(xs: list[int]) -> float:
    if len(xs) < 2:
        return 0.0
    return statistics.stdev(xs)


def _flip_rate(xs: list[int]) -> float:
    """Fraction of consecutive-pair disagreements. Same definition as
    eval/run.py's ``_flip_rate`` — re-implemented to avoid importing it
    from a private namespace and to keep the behavior frozen if the eval
    one ever changes."""
    if len(xs) < 2:
        return 0.0
    diffs = sum(1 for a, b in zip(xs, xs[1:]) if a != b)
    return diffs / (len(xs) - 1)


# ── Main ─────────────────────────────────────────────────────────────


def run_calibration(n_runs: int = 5) -> dict:
    items, header = _load_calibration()
    if not items:
        print("No calibration items found.", file=sys.stderr)
        return {}
    print(f"Calibrating: {len(items)} anchors × {n_runs} runs each "
          f"(types={header.get('anchor_counts', '?')})\n")
    t_start = time.time()

    per_anchor: list[dict] = []
    for i, item in enumerate(items, start=1):
        qid = item["id"]
        qtype = item["question_type"]
        print(f"[{i:>2}/{len(items)}] {qid} ({qtype}) — {item.get('question', '')[:60]}")
        result = _run_one_anchor(item, n_runs=n_runs)
        median_rel = int(round(statistics.median(result["rels"])))
        median_gnd = int(round(statistics.median(result["gnds"])))
        median_cit = int(round(statistics.median(result["cits"])))
        flip_rel = _flip_rate(result["rels"])
        flip_gnd = _flip_rate(result["gnds"])
        flip_cit = _flip_rate(result["cits"])
        sd_rel = _stdev(result["rels"])
        sd_gnd = _stdev(result["gnds"])
        sd_cit = _stdev(result["cits"])

        human = item.get("human_label", {}) or {}
        h_rel = human.get("relevance")
        h_gnd = human.get("groundedness")
        h_cit = human.get("citation_accuracy")

        def _within(a, b):
            if a is None or b is None:
                return None
            return abs(a - b) <= ACCURACY_TOLERANCE

        # Critical-error agreement: did we flag the same error class?
        # Just match SET of error labels (excl. NONE) at any run.
        judge_errs = set()
        for errs in result["errors"]:
            for e in errs:
                if e and e != "NONE":
                    judge_errs.add(e)
        human_errs = set(human.get("critical_errors", []) or [])
        human_errs.discard("NONE")
        crit_agreement = (judge_errs == human_errs)

        per_anchor.append({
            "id": qid,
            "question_type": qtype,
            "rule_based": result["rule_based"],
            "rels_runs": result["rels"],
            "gnds_runs": result["gnds"],
            "cits_runs": result["cits"],
            "median": {
                "relevance": median_rel,
                "groundedness": median_gnd,
                "citation_accuracy": median_cit,
            },
            "flip_rate": {
                "relevance": flip_rel, "groundedness": flip_gnd, "citation_accuracy": flip_cit,
            },
            "stdev": {"relevance": sd_rel, "groundedness": sd_gnd, "citation_accuracy": sd_cit},
            "human_label": human,
            "agreement": {
                "relevance": _within(median_rel, h_rel),
                "groundedness": _within(median_gnd, h_gnd),
                "citation_accuracy": _within(median_cit, h_cit),
                "critical_errors": crit_agreement,
            },
            "judge_errors": sorted(judge_errs) or ["NONE"],
        })
        rel_ok = "✓" if per_anchor[-1]["agreement"]["relevance"] else "✗"
        gnd_ok = "✓" if per_anchor[-1]["agreement"]["groundedness"] else "✗"
        print(
            f"          rel: judge={median_rel} human={h_rel} {rel_ok}   "
            f"gnd: judge={median_gnd} human={h_gnd} {gnd_ok}   "
            f"flip_rel={flip_rel:.2f}"
        )

    # Aggregate
    n = len(per_anchor)
    n_rel_ok = sum(1 for a in per_anchor if a["agreement"]["relevance"])
    n_gnd_ok = sum(1 for a in per_anchor if a["agreement"]["groundedness"])
    n_cit_ok = sum(1 for a in per_anchor if a["agreement"]["citation_accuracy"])
    n_err_ok = sum(1 for a in per_anchor if a["agreement"]["critical_errors"])
    rel_acc = n_rel_ok / n
    gnd_acc = n_gnd_ok / n
    cit_acc = n_cit_ok / n
    err_acc = n_err_ok / n
    mean_flip_rel = sum(a["flip_rate"]["relevance"] for a in per_anchor) / n
    mean_flip_gnd = sum(a["flip_rate"]["groundedness"] for a in per_anchor) / n

    # Confusion matrix at relevance ≥ PASS_THRESHOLD
    confusion: Counter = Counter()
    for a in per_anchor:
        h = a["human_label"].get("relevance")
        m = a["median"]["relevance"]
        if h is None:
            continue
        h_pass = h >= PASS_THRESHOLD
        m_pass = m >= PASS_THRESHOLD
        confusion[(h_pass, m_pass)] += 1
    tp = confusion.get((True, True), 0)
    tn = confusion.get((False, False), 0)
    fp = confusion.get((False, True), 0)
    fn = confusion.get((True, False), 0)

    summary = {
        "n_anchors": n,
        "n_runs_each": n_runs,
        "relevance_accuracy": rel_acc,
        "groundedness_accuracy": gnd_acc,
        "citation_accuracy_accuracy": cit_acc,
        "critical_error_agreement": err_acc,
        "mean_flip_rate_relevance": mean_flip_rel,
        "mean_flip_rate_groundedness": mean_flip_gnd,
        "tolerance_band": ACCURACY_TOLERANCE,
        "pass_threshold_relevance": PASS_THRESHOLD,
        "confusion": {
            "tp_human_pass_judge_pass": tp,
            "tn_human_fail_judge_fail": tn,
            "fp_human_fail_judge_pass": fp,
            "fn_human_pass_judge_fail": fn,
        },
        "elapsed_seconds": round(time.time() - t_start, 1),
        "header": header,
    }

    OUT_JSON.write_text(
        json.dumps({"summary": summary, "per_anchor": per_anchor}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # Human-readable report
    lines = [
        "# Judge Calibration Results",
        "",
        f"Anchors: {n} (×{n_runs} runs each)",
        f"Source: bootstrapped from `{header.get('source_file', '?')}` via `prior_verdict_mapping`",
        "",
        "## Acceptance gates (book Ch. 7)",
        "",
        f"| Axis | Accuracy (±{ACCURACY_TOLERANCE}) | Threshold | Pass? |",
        "|---|---|---|---|",
        f"| relevance | {rel_acc * 100:.1f}% | ≥ 80% | {'✓' if rel_acc >= 0.80 else '✗'} |",
        f"| groundedness | {gnd_acc * 100:.1f}% | ≥ 80% | {'✓' if gnd_acc >= 0.80 else '✗'} |",
        f"| citation_accuracy | {cit_acc * 100:.1f}% | (informational) | — |",
        f"| critical_error agreement | {err_acc * 100:.1f}% | (informational) | — |",
        "",
        f"Mean flip-rate (relevance): {mean_flip_rel * 100:.1f}% (target < 10%)",
        f"Mean flip-rate (groundedness): {mean_flip_gnd * 100:.1f}%",
        "",
        f"## Confusion matrix at relevance ≥ {PASS_THRESHOLD} (PASS gate)",
        "",
        "| | judge PASS | judge FAIL |",
        "|---|---|---|",
        f"| **human PASS** | TP={tp} | FN={fn} |",
        f"| **human FAIL** | FP={fp} | TN={tn} |",
        "",
        "## Per-anchor",
        "",
        "| ID | Type | rule | rel j/h | gnd j/h | cit j/h | flip_rel | agree |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for a in per_anchor:
        h = a["human_label"]
        m = a["median"]
        agree_pieces = []
        for axis in ("relevance", "groundedness", "citation_accuracy"):
            ok = a["agreement"][axis]
            agree_pieces.append("✓" if ok else "✗" if ok is False else "—")
        lines.append(
            f"| {a['id']} | {a['question_type']} | "
            f"{'rb' if a['rule_based'] else 'llm'} | "
            f"{m['relevance']}/{h.get('relevance', '—')} | "
            f"{m['groundedness']}/{h.get('groundedness', '—')} | "
            f"{m['citation_accuracy']}/{h.get('citation_accuracy', '—')} | "
            f"{a['flip_rate']['relevance']:.2f} | "
            f"{'/'.join(agree_pieces)} |"
        )
    lines.append("")
    lines.append("## Limitations")
    lines.append("")
    lines.append(
        "Anchors were derived programmatically from prior eval verdicts via "
        "`bootstrap_method=\"prior_verdict_mapping\"` (see "
        "`eval/bootstrap_calibration.py`). High disagreement here means EITHER "
        "the new judge is mis-scoring OR the bootstrap mapping was wrong. "
        "Replace items in `eval/calibration.json` with manually-reviewed "
        "labels (and set `bootstrap_method=\"human_reviewed\"`) before "
        "treating these accuracy numbers as a hard gate."
    )
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    print()
    print("=" * 72)
    print("CALIBRATION SUMMARY")
    print("=" * 72)
    print(f"  relevance accuracy        {rel_acc * 100:5.1f}%  (target ≥ 80%)")
    print(f"  groundedness accuracy     {gnd_acc * 100:5.1f}%")
    print(f"  citation_accuracy match   {cit_acc * 100:5.1f}%")
    print(f"  mean flip-rate (rel)      {mean_flip_rel * 100:5.1f}%  (target < 10%)")
    print(f"  confusion (PASS@{PASS_THRESHOLD}): TP={tp}  FP={fp}  FN={fn}  TN={tn}")
    print(f"  Wrote {OUT_JSON.relative_to(ROOT)}")
    print(f"  Wrote {OUT_MD.relative_to(ROOT)}")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=5,
                        help="Number of judge runs per anchor (default 5).")
    args = parser.parse_args()
    run_calibration(n_runs=args.runs)
