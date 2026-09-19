"""Oracle-context harness (Weekend-3 Phase C4).

Why this exists
===============
Book Chapter 1 §1.3 step 2 + Lab 4: "Run oracle-context: if answers recover with
gold context, the issue is retrieval/reranking; if not, it's generation/prompt."
This is the single highest-leverage diagnostic the book teaches. Without it, a
PARTIAL or DIFFERENT verdict could be caused by retrieval (wrong chunks fetched)
OR by generation (right chunks fetched but model failed to use them). You have
no way to tell which knob to turn.

What this script does
=====================
For each failing question (DIFFERENT or PARTIAL by default, configurable):

1. Load the gold supporting passages from must_cite_sources.
2. Pull those exact chunks directly from the vectorstore (bypass retrieval).
3. Format them as the QA context.
4. Run the QA prompt with this oracle context.
5. Score the answer with the same evidence-only judge from eval/run.py.
6. Compare oracle verdict vs normal verdict and label the root cause:
     - Oracle EQUIVALENT, normal not → RETRIEVAL_MISS (right chunks would fix it)
     - Both fail → GENERATION_PROBLEM (chunks are fine; prompt/model is the issue)
     - Both pass → noise/judge variance
     - Oracle worse than normal → odd; flag for inspection

Usage
=====
    # Re-run oracle on results from the last hard eval
    python eval/oracle.py --from eval/results_hard.json
    # Run for every question (slow but gives the full diagnostic table)
    python eval/oracle.py --from eval/results_hard.json --include-passing
    # Override which results file to load
    python eval/oracle.py --from eval/results.json

Outputs
=======
    eval/oracle_results.json
    eval/oracle_results.md
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from pipeline import _call_claude, _format_context                # noqa: E402
from claude_bridge import ClaudeCLIError                          # noqa: E402
from config import CLAUDE_MODEL_QUALITY                           # noqa: E402
from prompts import QA_SYSTEM, QA_USER                            # noqa: E402
# Gold-passage selection lives in eval/gold.py so run.py and oracle.py share one
# implementation. The local copy that used to live here matched source names
# exactly and so silently returned [] for the NFD-stored "5 KPIs …Café…" source
# (h01, h05, h06, h08) — see eval/gold.py for the full write-up.
from eval.gold import gold_chunks_for_question, GoldSourceMissing  # noqa: E402

# Reuse the new judge from run.py so verdicts are directly comparable
from eval.run import (
    _judge, _verdict_from_relevance, _normalize_question,
    _compute_recall, _nfc, EVAL_PROJECT,
)


# ── Root-cause classification ────────────────────────────────────────


def _classify(normal_verdict: str, oracle_verdict: str) -> str:
    """Map the (normal, oracle) verdict pair to a root-cause tag."""
    pos = ("EQUIVALENT",)
    partial = ("PARTIAL",)
    if normal_verdict in pos and oracle_verdict in pos:
        return "PASSES_BOTH"  # nothing to debug
    if normal_verdict not in pos and oracle_verdict in pos:
        return "RETRIEVAL_MISS"  # gold context would fix it
    if normal_verdict not in pos and oracle_verdict not in pos:
        if normal_verdict in partial and oracle_verdict not in partial:
            # Oracle worse — odd; flag explicitly
            return "ORACLE_WORSE_INVESTIGATE"
        return "GENERATION_PROBLEM"  # chunks fine; prompt/model is the issue
    if normal_verdict in pos and oracle_verdict not in pos:
        # Oracle should never be worse than normal in principle. Possible causes:
        # gold passages too short/missing context; judge variance.
        return "ORACLE_WORSE_INVESTIGATE"
    return "UNCLASSIFIED"


# ── Main loop ────────────────────────────────────────────────────────


def run_oracle(results_path: Path, include_passing: bool = False, judge_runs: int = 3):
    payload = json.loads(Path(results_path).read_text(encoding="utf-8"))
    # Support both new (with run_id) and old (raw list) formats
    if isinstance(payload, list):
        results = payload
    else:
        results = payload.get("results", [])

    if not results:
        print("No results to process.")
        return

    # Filter: failures only by default
    if include_passing:
        targets = list(results)
    else:
        targets = [
            r for r in results
            if r.get("verdict") in ("PARTIAL", "DIFFERENT", "ERROR")
            or any(e != "NONE" for e in (r.get("judge", {}).get("critical_errors") or []))
        ]

    if not targets:
        print("No failing questions found in input. Use --include-passing to run all.")
        return

    print(f"Oracle harness: running {len(targets)}/{len(results)} questions\n")
    t_start = time.time()

    oracle_results = []
    classification_counts: dict[str, int] = {}

    for i, r in enumerate(targets, 1):
        qid = r["id"]
        question = r["question"]
        qtype = r.get("question_type", "qa")
        normal_verdict = r.get("verdict", "ERROR")
        must_cite = r.get("must_cite_sources") or []

        print(f"[{i:>2}/{len(targets)}] {qid} ({qtype}) normal={normal_verdict}: {question[:55]}")

        if not must_cite:
            print("          no gold sources → cannot run oracle")
            oracle_results.append({
                "id": qid, "question": question, "question_type": qtype,
                "normal_verdict": normal_verdict,
                "oracle_verdict": "SKIP_NO_GOLD",
                "classification": "SKIP_NO_GOLD",
                "oracle_answer": "",
                "oracle_judge": None,
            })
            classification_counts["SKIP_NO_GOLD"] = classification_counts.get("SKIP_NO_GOLD", 0) + 1
            continue

        try:
            gold_chunks = gold_chunks_for_question(must_cite, project=EVAL_PROJECT)
        except GoldSourceMissing as e:
            # Loud, not silent: a named gold source that does not resolve is a
            # corpus/label mismatch, not a question to quietly skip.
            print(f"          GOLD SOURCE MISSING → skip ({e.source!r})")
            gold_chunks = []
        if not gold_chunks:
            print("          no gold chunks matched the wanted pages → skip")
            oracle_results.append({
                "id": qid, "question": question, "question_type": qtype,
                "normal_verdict": normal_verdict,
                "oracle_verdict": "SKIP_NO_CHUNKS",
                "classification": "SKIP_NO_CHUNKS",
                "oracle_answer": "",
                "oracle_judge": None,
            })
            classification_counts["SKIP_NO_CHUNKS"] = classification_counts.get("SKIP_NO_CHUNKS", 0) + 1
            continue

        evidence = _format_context(gold_chunks)

        # Generate with oracle context
        try:
            oracle_answer = _call_claude(
                CLAUDE_MODEL_QUALITY,
                QA_SYSTEM,
                QA_USER.format(context=evidence, question=question),
            )
        except ClaudeCLIError:
            oracle_answer = "[generation failed]"

        # Score
        norm = _normalize_question({
            "id": qid,
            "question": question,
            "expected_answer": r.get("expected_answer", ""),
            "question_type": qtype,
            "must_cite_sources": must_cite,
            "must_contain": r.get("must_contain", []),
            "expected_numbers": r.get("expected_numbers", []),
        })
        judge_out = _judge(norm, oracle_answer, evidence)
        oracle_verdict = _verdict_from_relevance(judge_out["relevance"])
        cls = _classify(normal_verdict, oracle_verdict)
        classification_counts[cls] = classification_counts.get(cls, 0) + 1

        print(f"          oracle={oracle_verdict}  →  {cls}")

        oracle_results.append({
            "id": qid, "question": question, "question_type": qtype,
            "normal_verdict": normal_verdict,
            "oracle_verdict": oracle_verdict,
            "classification": cls,
            "oracle_answer": oracle_answer,
            "oracle_judge": judge_out,
            "gold_chunk_count": len(gold_chunks),
        })

    elapsed = time.time() - t_start

    # ── Summary ──────────────────────────────────────────────────
    print("\n" + "=" * 78)
    print(f"Oracle harness — {len(oracle_results)} questions in {elapsed:.1f}s")
    print("=" * 78)
    for k in sorted(classification_counts):
        print(f"  {k:30s} {classification_counts[k]}")
    print("=" * 78)
    print()
    print("Interpretation:")
    print("  RETRIEVAL_MISS              → fix retrieval/reranking (chunks not surfaced)")
    print("  GENERATION_PROBLEM          → fix prompt/model (chunks fine; answer wrong)")
    print("  PASSES_BOTH                 → no debug needed (originally a flake or recovered)")
    print("  ORACLE_WORSE_INVESTIGATE    → gold passage gap or judge variance")
    print("  SKIP_NO_GOLD/SKIP_NO_CHUNKS → can't run oracle for this question")

    # ── Persist ──────────────────────────────────────────────────
    out_json = Path(__file__).parent / "oracle_results.json"
    out_json.write_text(
        json.dumps(oracle_results, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    out_md = Path(__file__).parent / "oracle_results.md"
    md = [
        "# Oracle-Context Harness Results",
        "",
        f"Source: `{results_path}`",
        f"Total examined: {len(oracle_results)}",
        "",
        "## Classification counts",
        "",
    ]
    for k in sorted(classification_counts):
        md.append(f"- **{k}**: {classification_counts[k]}")
    md.extend([
        "",
        "## Per-question",
        "",
        "| ID | Type | Normal | Oracle | Classification |",
        "|---|---|---|---|---|",
    ])
    for r in oracle_results:
        md.append(
            f"| {r['id']} | {r['question_type']} | {r['normal_verdict']} | "
            f"{r['oracle_verdict']} | {r['classification']} |"
        )
    md.extend(["", "## Oracle answers (for failed questions)", ""])
    for r in oracle_results:
        if r["classification"] in ("RETRIEVAL_MISS", "GENERATION_PROBLEM", "ORACLE_WORSE_INVESTIGATE"):
            md.append(f"### {r['id']} — {r['classification']}")
            md.append(f"**Q:** {r['question']}")
            md.append(f"**Normal verdict:** {r['normal_verdict']}  |  **Oracle verdict:** {r['oracle_verdict']}")
            md.append(f"**Oracle answer:** {r['oracle_answer'][:500]}{'...' if len(r['oracle_answer']) > 500 else ''}")
            md.append(f"**Oracle judge:** {r['oracle_judge']}")
            md.append("")
    out_md.write_text("\n".join(md), encoding="utf-8")

    print(f"\nDetailed: {out_json}")
    print(f"Summary:  {out_md}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--from", dest="from_path",
                   default=str(Path(__file__).parent / "results_hard.json"),
                   help="Path to results json from eval/run.py")
    p.add_argument("--include-passing", action="store_true",
                   help="Run oracle on every question, not just failures.")
    p.add_argument("--judge-runs", type=int, default=3)
    args = p.parse_args()
    run_oracle(Path(args.from_path),
               include_passing=args.include_passing,
               judge_runs=args.judge_runs)
