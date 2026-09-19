# Weekend-3 Remaining Work

This file is the implementation spec for everything not yet built in the Weekend-3 corrective plan. Read `CLAUDE.md` first for project context. The phases listed here are the four highest-leverage items still pending; the rest of the original plan (C2 probe, D2 adversarial suite, D3 abstention test, E2 GitHub Actions, E3 failure gallery, F drift, F canary) is deferred until this batch ships.

The previous batch (A1, A2, A3, B1, B2, B3, B5, C1, C3-partial, C4) is already merged. Do NOT re-implement those. The current state of the pipeline:

- `tracing.py` exists with `RagTrace`, `persist_trace`, `prompt_hash`, `hash_text`, `make_retrieved_records`.
- `citations.py` exists with `parse_citations`, `validate_citations`, `parse_and_validate`.
- `vectorstore.py` has `stable_chunk_id` and stores both `chunk_id` (stable hash) and `chunk_seq` (parser sequence) in metadata.
- `migrate_phase_a2.py` migrates legacy chunks in place.
- `eval/run.py` runs evidence-only judging with strict 5-axis JSON schema, N-run median, MRR/nDCG, citation validation, and writes per-question RagTraces to `data/traces/{run_id}/`.
- `eval/oracle.py` runs the oracle-context harness over failures.
- `config.py` has `CHUNKER_VERSION = 3`.

Now build the items below in order. After each phase, run the verification command. Don't move on if it fails.

---

## Phase 1 — G1 + G2: Groundedness gate on compose_capstone.py

**Why this matters.** `compose_capstone.py` calls Opus once with the full corpus and writes `business_plan.md` with no claim verification. The book (Chapter 6 §6.1) treats unsupported high-stakes claims as critical errors. The capstone deliverable currently ships with zero defense against hallucinated financial figures, fabricated KPIs, or invented operational details.

### G1: Claim extraction + entailment

Create `groundedness.py` at the project root.

**API:**

```python
def extract_claims(business_plan_md: str, model: str = "sonnet") -> list[dict]:
    """Split the business plan into atomic factual claims.

    Returns:
        [
          {
            "id": "c001",
            "section": "Financial Plan",
            "claim": "Labor costs are projected to drop 8% through AI scheduling.",
            "context": "...surrounding 2-3 sentences for evidence retrieval...",
          },
          ...
        ]

    Strategy: send the whole plan to Sonnet with a prompt that returns JSON.
    Use the same JSON parsing + retry pattern as eval/run.py's _parse_judge_json.
    Filter out claims that are framing/transition language rather than factual
    assertions (e.g. "This section discusses..."). Target 30-80 claims for a
    6000-word plan.
    """

def entail_claim(claim: dict, retrieved_chunks: list[dict],
                 model: str = "sonnet") -> dict:
    """Decide whether a claim is supported by retrieved evidence.

    Pull the top-3 grounding chunks via `retrieval.hybrid_search(claim["claim"],
    top_k=3, project="capstone")`, then ask Sonnet to score support on a strict
    JSON schema:

    {
      "support": "SUPPORTED" | "PARTIALLY_SUPPORTED" | "UNSUPPORTED",
      "evidence_chunk_ids": ["..."],
      "rationale": "<one sentence>"
    }

    Reuse claude_bridge.call_claude with the existing 1-retry-on-parse-failure
    pattern. Return:

    {
      "claim_id": claim["id"],
      "support": str,
      "evidence_chunk_ids": [...],
      "rationale": str,
      "retrieved": [{"source", "pages", "id", "text_hash"}],  # for trace
    }
    """

def run_groundedness_check(business_plan_md: str,
                           output_dir: Path,
                           project: str = "capstone") -> dict:
    """Full pipeline: extract → entail → write report. Returns summary stats.

    Outputs:
      output_dir/claims.json            — extracted claims
      output_dir/entailment.json        — per-claim verdicts
      output_dir/groundedness_report.md — human-readable report

    Summary returned:
      {
        "n_claims": int,
        "n_supported": int,
        "n_partial": int,
        "n_unsupported": int,
        "unsupported_rate": float,
        "high_risk_unsupported_rate": float,  # see below
      }

    High-risk sections: any claim whose `section` field contains "Financial",
    "Risk", "KPI", "Cost", "Revenue", or "Break-even".
    """
```

The `groundedness_report.md` should have:

```
# Groundedness Report
Plan: ...
Total claims: X
Supported: A (P%)
Partially: B (P%)
Unsupported: C (P%)

## Unsupported claims (review before submission)
- [Section] Claim text
  - Best retrieved evidence: source + pages
  - Why it failed: rationale

## High-risk section breakdown
| Section | Total | Supported | Unsupported |
|---|---|---|---|
| Financial Plan | ... | ... | ... |
```

### G2: Critical-error gate on the deliverable

Add a step to `compose_capstone.py` after `generate_business_plan` and before `convert_docx`:

```python
def step_groundedness_gate(plan_md: str) -> bool:
    """Run G1 check, write report, return True if it's safe to proceed."""
    from groundedness import run_groundedness_check
    summary = run_groundedness_check(plan_md, OUT_DIR, project=PROJECT)
    print(f"  Groundedness: {summary['n_supported']}/{summary['n_claims']} supported "
          f"({summary['unsupported_rate']*100:.1f}% unsupported)")
    print(f"  High-risk unsupported rate: {summary['high_risk_unsupported_rate']*100:.1f}%")
    if summary["high_risk_unsupported_rate"] > 0.05:
        print("  GATE FAILED: high-risk unsupported rate > 5%.")
        print("  Review deliverables/groundedness_report.md before exporting PDF.")
        return False
    return True
```

Wire it in `main()`:

```python
plan_md = generate_business_plan(corpus)
gate_ok = step_groundedness_gate(plan_md)
if not gate_ok:
    print("Aborting PDF/PPTX/XLSX generation. Fix unsupported claims first, then re-run with --force-export.")
    if "--force-export" not in sys.argv:
        return
docx = convert_docx()
...
```

Add `--force-export` CLI flag to `compose_capstone.py` that bypasses the gate.

**Verification:** `python -c "from groundedness import run_groundedness_check; ..."` runs without errors. The first real run on `business_plan.md` (when one exists) produces a non-empty `groundedness_report.md`.

---

## Phase 2 — B4 + B6: Judge determinism + calibration

### B4: Pin temperature 0 in claude_bridge

Modify `claude_bridge.py`:

1. Test if `claude -p` accepts `--temperature 0` (run `claude -p --help` once and check stdout).
2. If yes, append `--temperature`, `"0"` to the subprocess argv when caller passes `temperature=0` (default).
3. If no, document the gap in a comment and add a `seed` parameter as a fallback (CLI may accept `--seed`).

**API change:**

```python
def call_claude(model: str, system: str, user: str,
                timeout: int = 900,
                temperature: float = 0.0) -> str:
    ...
```

Update all callers in `eval/run.py`, `eval/oracle.py`, `pipeline.py`, `compose_capstone.py`, `groundedness.py` to default `temperature=0.0` for judges and remain at default (None / unspecified) for generation calls where some variability is OK.

**Verification:** Re-run the same judge call 3 times on the same input via `_judge_once`. Verdicts should match exactly when temperature pinning works. If they differ, log the gap.

### B6: Calibration set + harness

Create `eval/calibration.json`. 50 items, 10 per question type. Each item:

```json
{
  "id": "cal_qa_01",
  "question_type": "qa",
  "question": "...",
  "expected_answer": "...",
  "candidate_answer": "<a real answer the system might produce>",
  "evidence_chunks": [
    {"source": "...", "pages": "[4, 5]", "text": "..."}
  ],
  "human_label": {
    "relevance": 4,
    "groundedness": 5,
    "citation_accuracy": 4,
    "critical_errors": ["NONE"]
  },
  "notes": "calibration anchor — borderline rel=4 case"
}
```

Bootstrap process: pull 10 prior eval results per question type from `eval/results_hard.json`, label them yourself (the developer running this), and use those as the calibration anchors. Don't fabricate them.

Create `eval/calibrate.py`:

```python
"""Judge calibration harness (Weekend-3 Phase B6).

For each calibration item, run the judge N=5 times. Compare median verdict to
the human label. Compute:
    - per-axis accuracy: fraction of items where median == human ±1
    - per-axis flip-rate
    - per-axis dispersion (stdev of the 5 runs)
    - confusion matrix at relevance threshold 4 (PASS/FAIL gate)

Output:
    eval/calibration_results.json
    eval/calibration_results.md

Acceptance criteria for a usable judge:
    - relevance accuracy ≥ 80%
    - groundedness accuracy ≥ 80%
    - mean flip-rate < 10%

If those fail, the eval gate cannot be trusted. Don't tighten any other gate
until calibration passes.
"""

def run_calibration(n_runs: int = 5) -> dict:
    # Load eval/calibration.json
    # For each item, call _judge_llm_aggregated with n_runs
    # Compare to human_label
    # Aggregate into accuracy + flip-rate + confusion
    # Write JSON + MD
```

**Verification:** `python eval/calibrate.py` produces `eval/calibration_results.md` showing per-axis accuracy and flip-rate. Document the numbers in the MD; don't gate yet.

---

## Phase 3 — D1: Holdout split

Modify `eval/questions_hard.json` and `eval/run.py`:

1. Add `"holdout": true` field to 10 of the 25 questions in `questions_hard.json`. Pick a stratified mix: 2 per question_type. Choose questions you have NOT manually inspected the answers for during Weekend-2 tuning.

2. In `eval/run.py` add CLI flag:
```python
parser.add_argument("--holdout", choices=["all", "tuning", "holdout"], default="all",
                    help="Run all questions, only tuning set, or only holdout. "
                         "During development, use --holdout tuning. Before claiming "
                         "metrics, run --holdout holdout once and freeze.")
```

3. In `_normalize_question`, propagate `holdout: bool`. In the main loop, filter by the flag before iterating.

4. Update `results_hard.md` to label which subset the report covers.

**Verification:** `python eval/run.py --hard --holdout tuning` runs only the 15 tuning questions. `python eval/run.py --hard --holdout holdout` runs only the 10 holdout questions.

**Discipline rule (document this in CLAUDE.md):** Never tune retrieval, prompts, or judge prompts based on holdout results. Only tune on the tuning subset.

---

## Phase 4 — D4 + E1: Critical-error CI gate

### E1: regression_gate function

Create `eval/gate.py`:

```python
"""CI regression gate (Weekend-3 Phase E1).

Loads current eval/results_hard.json + eval/baseline.json, fails the build if
any tracked metric drops more than the per-metric tolerance OR any critical
error surfaces in a high-risk bucket.

Tracked metrics (with default tolerances):
    - retrieval_recall_pages         (max_drop: 0.05)
    - mrr_at_10                      (max_drop: 0.05)
    - ndcg_at_10                     (max_drop: 0.05)
    - judge_median_relevance         (max_drop: 1)    # integer scale
    - judge_median_groundedness      (max_drop: 1)
    - citation_page_accuracy_avg     (max_drop: 0.10)

Critical-error gate: ANY of these in the run blocks merge:
    - HALLUCINATION on any high-risk question
    - CITATION_WRONG on any question with must_cite_sources
    - WRONG_EVIDENCE on numeric questions
    - REFUSAL_ERROR on non-negative questions

Usage:
    python eval/gate.py --current eval/results_hard.json
    # exits 0 if pass, 1 if fail
"""

def regression_gate(current_path: Path,
                    baseline_path: Path,
                    tolerances: dict | None = None) -> int:
    # Load both JSONs
    # Compute metrics for current run
    # Compare to baseline
    # Apply critical-error rule
    # Print pass/fail per metric
    # Return exit code
```

### D4: Update slow pytest assertion

Edit `tests/test_smoke.py` (the `@pytest.mark.slow` test). Replace:

```python
assert equivalent_count >= 14
```

with:

```python
from eval.gate import regression_gate
exit_code = regression_gate(
    current_path=Path("eval/results_hard.json"),
    baseline_path=Path("eval/baseline.json"),
)
assert exit_code == 0, "regression gate failed; see stdout"
```

Create `eval/baseline.json` initially as a copy of the current `results_hard.json` summary. Once Phase 1 + Phase 2 land and the new metrics stabilize, regenerate it.

**Verification:** `python eval/gate.py --current eval/results_hard.json` returns 0. Manually corrupt `eval/results_hard.json` (drop one metric), confirm it returns 1. Restore.

---

## Final acceptance criteria for this batch

After all four phases land:

1. `pytest -m "not slow"` still passes (13 tests).
2. `python eval/calibrate.py` produces a calibration report with relevance accuracy ≥ 80% (or documents the gap clearly).
3. `python eval/run.py --hard --holdout tuning` completes successfully and writes results.
4. `python eval/gate.py --current eval/results_hard.json` returns exit 0 against a fresh baseline.
5. `python compose_capstone.py` runs the new G1 step and either passes the gate or writes `groundedness_report.md` and aborts cleanly.

Update `CLAUDE.md`'s "Recent Changes" section with a Weekend-3 entry summarizing what shipped.
