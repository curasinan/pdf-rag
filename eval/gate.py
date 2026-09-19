"""CI regression gate (Weekend-3 Phase E1).

Loads ``eval/results_hard.json`` and ``eval/baseline.json``, fails the build if
any tracked metric drops more than its per-metric tolerance OR any critical
error surfaces in a high-risk bucket.

Why this lives in eval/, not at the project root
================================================
Chapter 10 §10.2 of the book treats the regression gate as part of the eval
contract: the eval owns the metric definitions, so the gate that compares two
eval runs ships next to the harness that produced them. New metrics added to
``run.py`` show up here automatically by being read out of the JSON envelope.

Tracked metrics + tolerances
============================
``retrieval_recall_pages``     max_drop 0.05
``mrr_at_10``                  max_drop 0.05
``ndcg_at_10``                 max_drop 0.05
``judge_median_relevance``     max_drop 1     (1-5 integer scale)
``judge_median_groundedness``  max_drop 1
``citation_page_accuracy_avg`` max_drop 0.10

Override per-metric tolerances by passing a dict to ``regression_gate``.

Critical-error gate
===================
Any of these in the current run blocks merge:
- ``HALLUCINATION``  on any high-risk question (numeric / qa with must_cite_sources)
- ``CITATION_WRONG`` on any question with must_cite_sources
- ``WRONG_EVIDENCE`` on numeric questions
- ``REFUSAL_ERROR``  on non-negative questions

A critical-error trip blocks the merge regardless of metric movement — even if
recall and judge medians improved, an unbreakable hallucination is a release
blocker.

Absolute floors + judge-outage (F11)
====================================
Beyond the baseline delta comparison, the current run is checked on its own:
- ``judge_median_relevance`` and ``judge_median_groundedness`` must clear an
  absolute floor of 3.0. This catches a judge-median collapse (5 → 1) even when
  the baseline is a legacy schema that carries no judge fields and the delta
  comparison would otherwise skip the metric.
- Any LLM-judged question whose judge relevance came back ``None`` (a judge
  outage) fails the gate — the old behavior skipped those rows and passed a run
  in which no answer was actually scored.

Schema tolerance (hardened in F11)
==================================
Both new (Weekend-3 ``{"run_id", "subset", "results": [...]}``) and old
(Weekend-2 list of result dicts) JSON shapes are accepted. A metric that is
absent on BOTH sides is skipped (nothing to compare). A metric present in the
current run but absent from the baseline is skipped *with a loud warning* to
regenerate the baseline — it is NOT silently ignored. A metric absent from the
current run but present in the baseline is a hard FAIL (the run lost a metric),
not a skip — that asymmetric case was the original fail-open hole.

Usage
=====
::

    python eval/gate.py --current eval/results_hard.json
    # exits 0 if pass, 1 if any metric or critical-error rule fails

The gate is designed to be cheap: it doesn't run any LLM call. All the
expensive judging happened during ``eval/run.py``; this script just compares
the resulting JSON.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


# ── Defaults ─────────────────────────────────────────────────────────


DEFAULT_TOLERANCES: dict[str, float] = {
    "retrieval_recall_pages": 0.05,
    "mrr_at_10": 0.05,
    "ndcg_at_10": 0.05,
    "judge_median_relevance": 1.0,
    "judge_median_groundedness": 1.0,
    "citation_page_accuracy_avg": 0.10,
}

# Absolute floors (finding F11). These are checked against the *current* run alone,
# independent of the baseline, so a judge-median collapse (5 → 1) is caught even
# when the shipped baseline is a legacy schema that carries no judge fields and the
# delta comparison would otherwise SKIP the metric. A median relevance/groundedness
# below 3 means the *typical* answer is DIFFERENT / ungrounded — a release blocker
# on its own terms. A metric that the current run doesn't carry is not floor-checked.
ABSOLUTE_FLOORS: dict[str, float] = {
    "judge_median_relevance": 3.0,
    "judge_median_groundedness": 3.0,
}

# Question types whose verdict comes from the LLM judge (rule-based judges always
# emit an integer relevance, so a None there means a real judge outage — F11).
_LLM_JUDGED_TYPES = {"qa", "synthesis", "page_lookup"}

# Critical-error rules — a tuple of (error_label, predicate over the question record)
def _is_high_risk_question(r: dict) -> bool:
    """A question is "high risk" for the hallucination rule if it has gold
    sources to cite (numeric / qa with must_cite_sources). Negative questions
    are intentionally excluded — there's no "right answer" to hallucinate."""
    qtype = r.get("question_type", "")
    if qtype == "negative":
        return False
    return bool(r.get("must_cite_sources"))


def _has_must_cite(r: dict) -> bool:
    return bool(r.get("must_cite_sources"))


CRITICAL_RULES: list[tuple[str, str, callable]] = [
    ("HALLUCINATION",  "on any high-risk question",       _is_high_risk_question),
    ("CITATION_WRONG", "on any must-cite question",        _has_must_cite),
    ("WRONG_EVIDENCE", "on numeric questions",             lambda r: r.get("question_type") == "numeric"),
    ("REFUSAL_ERROR",  "on non-negative questions",        lambda r: r.get("question_type") != "negative"),
]


# ── Loaders ──────────────────────────────────────────────────────────


def _load_results(path: Path) -> tuple[list[dict], dict]:
    """Return ``(results_list, envelope_meta)``. Tolerates both schemas."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return raw, {"schema": "legacy_list"}
    if isinstance(raw, dict) and "results" in raw:
        return raw["results"], {k: v for k, v in raw.items() if k != "results"}
    raise ValueError(f"Unrecognized eval JSON shape at {path}")


def _safe_get(d: dict | None, *keys, default=None):
    """Walk a nested dict, returning ``default`` if any key is missing."""
    cur = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


# ── Metric extraction ────────────────────────────────────────────────


def _compute_metrics(results: list[dict], meta: dict | None = None) -> dict:
    """Pull per-run aggregate metrics out of a list of result records.

    Skips any metric the schema doesn't carry — old eval output has fewer
    fields than current. Returned values are floats or None."""
    if not results:
        return {}

    # Recall (page-level)
    recall_applicable = [r for r in results if _safe_get(r, "recall", "applicable")]
    if recall_applicable:
        n_pages = sum(1 for r in recall_applicable if _safe_get(r, "recall", "pages_full"))
        retrieval_recall_pages = n_pages / len(recall_applicable)
    else:
        retrieval_recall_pages = None

    # MRR / nDCG
    mrrs = [r["mrr_at_10"] for r in results if r.get("mrr_at_10") is not None]
    ndcgs = [r["ndcg_at_10"] for r in results if r.get("ndcg_at_10") is not None]
    mrr_avg = sum(mrrs) / len(mrrs) if mrrs else None
    ndcg_avg = sum(ndcgs) / len(ndcgs) if ndcgs else None

    # Judge medians
    rels = [_safe_get(r, "judge", "relevance") for r in results]
    rels = [x for x in rels if isinstance(x, (int, float))]
    gnds = [_safe_get(r, "judge", "groundedness") for r in results]
    gnds = [x for x in gnds if isinstance(x, (int, float))]
    judge_median_relevance = statistics.median(rels) if rels else None
    judge_median_groundedness = statistics.median(gnds) if gnds else None

    # Citation page accuracy avg
    cites = [_safe_get(r, "citation_validation", "page_accuracy") for r in results]
    cites = [x for x in cites if isinstance(x, (int, float))]
    citation_page_accuracy_avg = sum(cites) / len(cites) if cites else None

    # Claim-to-citation support. REPORTED, never delta-checked: it is absent from
    # DEFAULT_TOLERANCES by design, and the delta loop iterates that dict, so this
    # metric cannot fail a build. It contains an LLM stage, and a non-deterministic
    # gate-tracked metric is exactly how the gate went permanently red before.
    # Promotion criterion is written down in CLAUDE.md so it cannot rot into a TODO.
    cs = [_safe_get(r, "citation_claim_support", "claim_support_avg") for r in results]
    cs = [x for x in cs if isinstance(x, (int, float))]
    citation_claim_support_avg = sum(cs) / len(cs) if cs else None

    # Judge-outage detector (F11): an LLM-judged question whose schema carries a
    # judge dict but whose relevance came back None means the judge call failed
    # (CLI auth expiry, rate limit) — the answer was effectively never judged.
    # This must FAIL the gate; the old behavior SKIPped the None judge rows and
    # passed a run in which no answer was scored.
    n_judge_failures = sum(
        1 for r in results
        if isinstance(r.get("judge"), dict)
        and _safe_get(r, "judge", "relevance") is None
        and r.get("question_type") in _LLM_JUDGED_TYPES
    )

    return {
        "retrieval_recall_pages": retrieval_recall_pages,
        "mrr_at_10": mrr_avg,
        "ndcg_at_10": ndcg_avg,
        "judge_median_relevance": judge_median_relevance,
        "judge_median_groundedness": judge_median_groundedness,
        "citation_page_accuracy_avg": citation_page_accuracy_avg,
        # Meta (not delta-compared; used for absolute checks):
        "_n_results": len(results),
        "_n_judge_failures": n_judge_failures,
        "_citation_claim_support_avg": citation_claim_support_avg,
        "_citation_support_runs": (meta or {}).get("citation_support_runs"),
        "_citation_support_scope": (meta or {}).get("citation_support_scope"),
    }


# ── Critical-error scan ──────────────────────────────────────────────


def _critical_error_set(results: list[dict]) -> dict[tuple[str, str], str]:
    """Map ``(question_id, label) -> description`` for every triggered rule."""
    found: dict[tuple[str, str], str] = {}
    for label, where, pred in CRITICAL_RULES:
        for r in results:
            errs = _safe_get(r, "judge", "critical_errors", default=[]) or []
            if not isinstance(errs, list):
                errs = [errs]
            if label in errs and pred(r):
                qid = r.get("id", "?")
                found[(qid, label)] = (
                    f"{label} {where}: question {qid} ({r.get('question_type', '?')})"
                )
    return found


def _critical_error_violations(results: list[dict],
                               baseline_results: list[dict] | None = None) -> list[str]:
    """Critical-error violations, measured as a *regression* against the baseline.

    Absolute blocking was the original design, and it is right for the
    deliverable groundedness gate — a hallucinated figure in a business plan is
    unacceptable regardless of history. It is wrong for a *regression* gate,
    because it conflates "this system has known issues" with "this change made it
    worse". Once the baseline itself contains any critical error the gate is
    permanently red, which makes it useless as a signal: the regenerated baseline
    trips six rules that two of three judge runs agree on.

    So: a critical error already present in the baseline for the same question is
    pre-existing and reported as carried-over, not blocking. A *new* one — a new
    question, or a new label on a known-bad question — blocks. Passing no baseline
    restores the old absolute behaviour.
    """
    current = _critical_error_set(results)
    if baseline_results is None:
        return sorted(current.values())
    known = set(_critical_error_set(baseline_results))
    return sorted(desc for key, desc in current.items() if key not in known)


def _critical_errors_carried_over(results: list[dict],
                                  baseline_results: list[dict]) -> list[str]:
    """Pre-existing critical errors — reported for visibility, not blocking."""
    current = _critical_error_set(results)
    known = set(_critical_error_set(baseline_results))
    return sorted(desc for key, desc in current.items() if key in known)


# ── Gate ─────────────────────────────────────────────────────────────


def _warn_hash_drift(field: str, what: str, cur: str | None, base: str | None) -> None:
    """Report comparability drift for one hash field. WARNS, never fails.

    All four states are handled explicitly, including ``neither side has it``
    (stay silent — symmetric absence establishes nothing but claims nothing).
    The three-branch original was duplicated per field once, and the duplicate
    shipped with the ``cur and not base`` arm missing, so the one case that
    matters most on a fresh field — a baseline that predates it — fell through
    silently. One helper, called twice, cannot drift apart that way.
    """
    if cur and base and cur != base:
        print(f"[gate] WARN — {what} changed since baseline ({base} -> {cur}); "
              f"judge medians and critical-error counts are NOT strictly comparable. "
              f"Regenerate the baseline.")
    elif base and not cur:
        print(f"[gate] WARN — current results carry no {field}; cannot verify "
              f"the {what} matches the baseline's.")
    elif cur and not base:
        # A baseline written before the field existed. Comparability is unknown,
        # not established, and saying nothing would reproduce the very blindness
        # the field was added to remove.
        print(f"[gate] WARN — baseline predates {field} (current is {cur}); "
              f"cannot verify it was scored under the same {what}. "
              f"Regenerate the baseline.")


def regression_gate(
    current_path: Path | str,
    baseline_path: Path | str,
    tolerances: dict[str, float] | None = None,
) -> int:
    """Compare ``current`` to ``baseline`` and exit-code 0 (pass) or 1 (fail).

    Parameters
    ----------
    current_path
        Path to ``eval/results_hard.json`` (or any eval output JSON).
    baseline_path
        Path to ``eval/baseline.json`` (a snapshot of a known-good run). If the
        file is absent the gate falls through to critical-error checking only
        and prints a warning — we'd rather pass on a fresh repo than block
        every clone.
    tolerances
        Per-metric ``max_drop`` overrides. Falls back to ``DEFAULT_TOLERANCES``.

    Returns
    -------
    int
        0 on pass, 1 on fail. ``main`` translates to ``sys.exit``.
    """
    tols = dict(DEFAULT_TOLERANCES)
    if tolerances:
        tols.update(tolerances)

    current_path = Path(current_path)
    baseline_path = Path(baseline_path)

    if not current_path.exists():
        print(f"[gate] FAIL — current results not found: {current_path}")
        return 1

    cur_results, cur_meta = _load_results(current_path)
    cur_metrics = _compute_metrics(cur_results, cur_meta)

    print(f"[gate] current  : {current_path} ({len(cur_results)} questions, schema={cur_meta.get('schema', 'envelope')})")

    base_metrics: dict | None = None
    if baseline_path.exists():
        base_results, base_meta = _load_results(baseline_path)
        base_metrics = _compute_metrics(base_results, base_meta)
        print(f"[gate] baseline : {baseline_path} ({len(base_results)} questions, schema={base_meta.get('schema', 'envelope')})")
        # A judge edit moves judge medians, citation_accuracy and critical-error
        # counts without touching the system under test. Warn, don't fail: blocking
        # would put every legitimate judge improvement behind a mandatory
        # regeneration, which contradicts this gate's block-on-NEW-problems design.
        #
        # Two hashes, because neither covers the other and BOTH have hidden a real
        # scoring change on byte-identical answers:
        #   judge_prompt_hash — the LLM rubric text
        #   judge_code_hash   — the judge logic in Python (rule judges, the
        #                       page_lookup phrase matcher, vote filtering,
        #                       median/majority aggregation, verdict mapping)
        _warn_hash_drift(
            "judge_prompt_hash", "judge rubric",
            cur_meta.get("judge_prompt_hash"), base_meta.get("judge_prompt_hash"))
        _warn_hash_drift(
            "judge_code_hash", "judge code",
            cur_meta.get("judge_code_hash"), base_meta.get("judge_code_hash"))
    else:
        print(f"[gate] baseline : MISSING ({baseline_path}) — skipping metric comparison (critical-error check still runs)")

    # ── Metric comparisons ───────────────────────────────────────
    # Three distinct None cases, only one of which is safe to skip (F11):
    #   • absent on BOTH sides         → symmetric, nothing to compare → SKIP
    #   • present current, absent base → baseline is a stale/legacy schema →
    #                                     SKIP but warn loudly (regenerate baseline)
    #   • absent current, present base → the current run LOST a metric the baseline
    #                                     had (e.g. judge collapsed to None) → FAIL
    failed_metrics: list[str] = []
    skipped_both: list[str] = []
    baseline_missing: list[str] = []
    print()
    print(f"  {'metric':<32} {'current':>10} {'baseline':>10} {'drop':>10} {'tol':>8}  result")
    print(f"  {'-'*32} {'-'*10} {'-'*10} {'-'*10} {'-'*8}  ------")
    for name, max_drop in tols.items():
        cur = cur_metrics.get(name)
        base = base_metrics.get(name) if base_metrics else None
        cur_s = "n/a" if cur is None else f"{cur:.3f}"
        base_s = "n/a" if base is None else f"{base:.3f}"
        if cur is None and base is not None:
            # Asymmetric loss — the dangerous fail-open case.
            failed_metrics.append(f"{name}: current run is missing a metric the baseline carries")
            print(f"  {name:<32} {cur_s:>10} {base_s:>10} {'—':>10} {max_drop:>8}  FAIL(missing)")
            continue
        if base is None and cur is not None:
            baseline_missing.append(name)
            print(f"  {name:<32} {cur_s:>10} {base_s:>10} {'—':>10} {max_drop:>8}  SKIP(stale-base)")
            continue
        if cur is None and base is None:
            skipped_both.append(name)
            print(f"  {name:<32} {cur_s:>10} {base_s:>10} {'—':>10} {max_drop:>8}  SKIP(absent)")
            continue
        drop = base - cur  # positive = regression
        passed = drop <= max_drop
        marker = "PASS" if passed else "FAIL"
        if not passed:
            failed_metrics.append(f"{name}: dropped {drop:.3f} (tol {max_drop})")
        print(f"  {name:<32} {cur:>10.3f} {base:>10.3f} {drop:>+10.3f} {max_drop:>8.3f}  {marker}")

    # ── Absolute floors (baseline-independent) ───────────────────
    print()
    floor_violations: list[str] = []
    for name, floor in ABSOLUTE_FLOORS.items():
        cur = cur_metrics.get(name)
        if cur is None:
            continue
        if cur < floor:
            floor_violations.append(f"{name}={cur:.3f} below absolute floor {floor}")
            print(f"  [floor] {name:<28} {cur:>10.3f}  <  {floor:<6}  FAIL")
        else:
            print(f"  [floor] {name:<28} {cur:>10.3f}  >= {floor:<6}  PASS")

    # ── Claim support: reported, never gated ─────────────────────
    cs_cur = cur_metrics.get("_citation_claim_support_avg")
    if cs_cur is not None:
        runs_c, runs_b = (cur_metrics.get("_citation_support_runs"),
                          base_metrics.get("_citation_support_runs") if base_metrics else None)
        scope_c, scope_b = (cur_metrics.get("_citation_support_scope"),
                            base_metrics.get("_citation_support_scope") if base_metrics else None)
        cs_base = base_metrics.get("_citation_claim_support_avg") if base_metrics else None
        print()
        if cs_base is None:
            print(f"  citation_claim_support_avg    {cs_cur:>10.3f}  (reported, not gated; "
                  f"no baseline value)")
        elif runs_c != runs_b or scope_c != scope_b:
            # The value depends on both. Comparing across them is the same class of
            # error as comparing judge scores across rubrics, so refuse rather than
            # print a delta that looks meaningful.
            print(f"  citation_claim_support_avg    {cs_cur:>10.3f}  SKIP(incomparable: "
                  f"runs {runs_b} vs {runs_c}, scope {scope_b} vs {scope_c})")
        else:
            print(f"  citation_claim_support_avg    {cs_cur:>10.3f}  baseline {cs_base:.3f}  "
                  f"({cs_cur - cs_base:+.3f}, reported, not gated)")

    # ── Judge-outage check (baseline-independent) ────────────────
    n_judge_failures = cur_metrics.get("_n_judge_failures", 0) or 0
    if n_judge_failures:
        floor_violations.append(
            f"{n_judge_failures} LLM-judged question(s) had no judge verdict "
            f"(judge outage) — run not scorable"
        )
        print(f"  [judge] {n_judge_failures} LLM-judged question(s) unscored  FAIL")

    # ── Critical-error scan ──────────────────────────────────────
    print()
    crit_violations = _critical_error_violations(cur_results, base_results)
    carried = _critical_errors_carried_over(cur_results, base_results) if base_results else []
    if crit_violations:
        print("[gate] CRITICAL ERRORS (NEW since baseline — blocking):")
        for v in crit_violations:
            print(f"   - {v}")
    else:
        print("[gate] critical errors: no new ones since baseline")
    if carried:
        print(f"[gate] carried over from baseline (not blocking, {len(carried)} — "
              f"pre-existing defects worth fixing):")
        for v in carried:
            print(f"   · {v}")

    # ── Decision ─────────────────────────────────────────────────
    print()
    if baseline_missing:
        print(
            f"[gate] WARNING: baseline lacks {len(baseline_missing)} tracked metric(s) "
            f"{baseline_missing} — these were NOT delta-checked. Regenerate "
            f"eval/baseline.json from a current-schema run so drops are caught."
        )
    if failed_metrics or crit_violations or floor_violations:
        print("[gate] RESULT: FAIL")
        if failed_metrics:
            print(f"  failed metrics: {failed_metrics}")
        if floor_violations:
            print(f"  floor/judge violations: {floor_violations}")
        if crit_violations:
            print(f"  critical violations: {len(crit_violations)}")
        return 1
    if skipped_both or baseline_missing:
        skipped = skipped_both + baseline_missing
        print(f"[gate] RESULT: PASS (with {len(skipped)} skipped metric(s): {skipped})")
    else:
        print("[gate] RESULT: PASS")
    return 0


# ── CLI ──────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--current",
        default=str(ROOT / "eval" / "results_hard.json"),
        help="Path to the current eval results JSON. Default eval/results_hard.json.",
    )
    parser.add_argument(
        "--baseline",
        default=str(ROOT / "eval" / "baseline.json"),
        help="Path to the baseline results JSON. Default eval/baseline.json.",
    )
    args = parser.parse_args()
    sys.exit(regression_gate(args.current, args.baseline))


if __name__ == "__main__":
    main()
