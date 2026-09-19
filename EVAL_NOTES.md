# Eval and judge notes — how the numbers are made

Extracted from `CLAUDE.md` (Aug 2026) to keep the project memory light, the same way
`ABLATION_NOTES.md` was extracted. Read this before editing `eval/run.py`,
`eval/gate.py`, the judge rubric, or before quoting any eval metric. The binding
rules stay in `CLAUDE.md`; this file holds the full reasoning and the tables.

Companions: `HISTORY.md` (chronological changelogs), `ABLATION_NOTES.md` (ablation
build traps), `ABLATION_WRITEUP.md` (the study itself).

---

## Baseline lineage and gate semantics (Aug 2026)

- **`eval/baseline.json` regenerated** from `--arm A --judge-runs 3 --judge-evidence
  own`, which also produced `eval/results_hard.json` — the gate's default path, which
  had never existed. The legacy file (kept as `eval/baseline_legacy.json`) lacked
  `mrr_at_10`, `ndcg_at_10`, `judge`, `citation_validation` and `holdout`, so the gate
  was silently SKIPping five of six tracked metrics. Later re-frozen from run
  `freeze2` (see the freeze section below and in `CLAUDE.md`).
- **Critical errors are MAJORITY-voted across judge runs, not unioned**
  (`_judge_llm_aggregated`). Scores already used the median, so one dissenting run
  could not move them — but it *could* brand an answer with a gate-blocking error, and
  the false-positive count grew with `--judge-runs` by construction (10 violations, 4
  flagged by exactly 1 of 3, on answers judged EQUIVALENT at relevance 4-5). Published
  ablation error counts predate this. Since `freeze2` the vote is also SPAN-AWARE
  (below).
- **The regression gate blocks on NEW critical errors, not all of them**
  (`eval/gate.py`). Absolute blocking is right for the deliverable groundedness gate
  but wrong for a *regression* gate, where it conflates "this system has known issues"
  with "this change made it worse" — it was permanently red and useless. Carried-over
  errors print without blocking; a new question or label blocks; no baseline restores
  absolute behaviour.

---

## The six "carried-over defects" were the rubric, not the system (Aug 2026)

Full account in `HISTORY.md`. `CITATION_WRONG` h02/h06/h17 + `HALLUCINATION`
h03/h05/h07, adjudicated against the actual chunk text: **zero survived**, and two
were provably founded on text the answer never contained. All six sat at exactly
2-of-3, never unanimous, so one bad vote was decisive. Four judge fixes, **none in
the generator**: label definitions, telling the judge chunks span page ranges,
removing "penalize verbosity", and requiring every accusing vote to quote the span it
accuses. Re-judge on the same cached answers: **6 → 0 blocking errors, none new**,
every clearance unanimous, verdicts unchanged 24/25, retrieval byte-identical.
h05/h06 are holdout and cleared without ever being looked at.

---

## The clearance holds under fresh generation (COMPLETION_PLAN Phase 2)

The six-error clearance re-judged CACHED answers, so it could not separate "the rubric
was wrong" from "those answers were lucky". Fresh generations (separate `--cache-dir`),
fresh judging, tuning subset: **14/15 EQUIVALENT + 1 PARTIAL (h01), medians 5/5/5,
flip-rate 0.000, citation page-accuracy 0.992, critical errors none** —
verdict-for-verdict identical to `judgefix`, retrieval byte-identical on all 15 (arm A's
retriever is deterministic, re-confirmed). `eval/results_hard_verify{1,2}.{json,md}`.

**It took two passes.** `verify1` failed with `WRONG_EVIDENCE` on h01, whose two
generations say the same correct thing — the context does not contain KPI #5 — but one
wrote `table turn time` and the other `table-turn speed`. `must_contain` is
`['table turn', 'page 8']`; `page 8` is genuinely absent (retrieval never surfaced it),
and `_judge_page_lookup` drops to 1/1/1 + a gate-blocking error only when **every**
phrase misses. One hyphen separated 3 from a blocked gate.

`_phrase_satisfied` now retries with word separators folded, after the plain substring
test fails: a literal test on `table turn` is an **orthography** test, not a content
test. Replayed old-vs-new over every stored answer in all 19 result files (193
phrase-checks) it changes **exactly one cell** and regresses none, and never touches
h05 — the only other multi-word phrase, a holdout question, already satisfying
`seat hour`. Designed on h01 alone; D1 intact.

It does not hide the failure: h01 stays PARTIAL 3/3/3 with `page 8` unsatisfied,
`pages_full: false`, `MRR=0.0`.

`tools/probe_judge.py` passed as the phase's entry gate and was deliberately NOT re-run
after the fix: both prompt hashes were byte-identical, so it would have re-tested an
untouched rubric — which is exactly the coverage gap the freeze investigation later
closed (the probe now covers the rule judges; see the next section).

---

## Phase 6 freeze mechanics — the judge fixed in both directions (Aug 2026)

The frozen numbers and the two binding rules live in `CLAUDE.md`; the full narrative
with the planted-answer tables and the h07 adjudication is in `HISTORY.md` ("Task
20"). What changed in the judge, code only — the rubric text is byte-identical
(`judge_prompt_hash ba29d7420a62` throughout; `judge_code_hash` 6abaef139a17 →
587f0fb8e468):

- **`_judge_page_lookup` all-miss** now splits on an abstention detector
  (`_ABSTENTION_RE`): context-lack wording → `FORMAT_FAIL` 1/1/1 (named
  non-answer, F13's semantics one judge over); otherwise `WRONG_EVIDENCE`
  1/1/1. The detector anchors on the CONTEXT lacking the fact, never
  first-person inability — norerank h04 hedges "I can't pinpoint a single page
  number" around a confidently wrong worked example and must keep firing.
- **`_judge_page_lookup` partial branch** finally catches the wrong page: a
  missed `page N` assertion on a non-abstaining answer that cites pages →
  `CITATION_WRONG` 2/2/2, gate-blocking on must-cite questions. Chunk-grain
  citations satisfy subset-first, so h06's ceiling stays a ceiling, not an
  error. Residual, documented in the docstring: a fabrication that also plants
  abstention wording escapes with the softer label (axes still floor at 1-2).
- **Critical-error voting is span-aware** (`_max_same_span_votes`): a label
  survives only if a single span collects the majority, where "same span"
  means the quoted accusations overlap in the candidate. Empty-quote votes are
  wildcards, so pre-quote-era `per_run` rows re-aggregate byte-identically.
- **`tools/probe_judge.py` now probes every judge** — rule judges and vote
  aggregation run offline (`--rules-only`), the LLM plants remain. Run pre-fix
  it went red on exactly the three defects; blast-radius replay over 29 stored
  result files (13 rule cells, 174 aggregations) changed exactly 3 cells, all
  designed targets.

Mid-run trivia that validated the plumbing: the CLI hit a session limit at h19-h21;
the checkpoint kept the 22 scored rows, `--resume` retried the three ERROR rows after
the reset, and the inherited rows carried the same `judge_code_hash` so no staleness
warning fired.

---

## `judge_code_hash` — implementation traps (Aug 2026)

`judge_prompt_hash` covers rubric TEXT only, so every judge decision made in Python was
invisible to `eval/gate.py`. That hid two real scoring changes on byte-identical
answers, both leaving the hash at `ba29d7420a62`: unioned → **majority-voted** critical
errors (6 blocking → 0), and `_phrase_satisfied` folding separators (h01 1/1/1 → 3/3/3).
`judge_code_hash` (`tracing.code_hash` over `eval/run._JUDGE_CODE_SYMBOLS`) covers the
whole judge decision surface — rule judges, dispatch, phrase matcher,
parse/vote-filter/aggregate, `_verdict_from_relevance` — and rides in the envelope, each
record, and the trace.

**Correction to an earlier claim: 15 of 25, not 9.** page_lookup is a HYBRID (rule
decides 1-vs-3, LLM only 4-vs-5), so 6 page_lookup + 5 numeric + 4 negative route
through rule code and both hashes are load-bearing on six at once. Only 9 (numeric +
negative) never reach an LLM. h01 sat in the 6 that "9" excluded.

Four traps, each of which silently breaks the naive version — **full reasoning in the
`tracing.normalized_source` / `_code_fingerprint` docstrings, read them before editing**:
hash normalized AST not raw source (these functions are ~78% prose; also buys
CRLF-insensitivity, at the price of `ast.unparse` being a CPython detail); sort sets
(`_VALID_ERRORS` is a `set` and string hashing is per-process randomized, so unsorted it
warns forever); fingerprint regexes as `(pattern, flags)` (`.pattern` is blind to a
dropped `IGNORECASE`); and RAISE on unknown types rather than skipping. `_expand_pages`
is covered although it lives in `citations.py`.

Warn-never-fail is preserved through one `_warn_hash_drift` helper used for both hashes
— the duplicated three-branch version had already shipped once missing its
`baseline predates the field` arm. `--resume` warns when inherited records carry a
different stamp.

---

## Second generation seed — the full table (Aug 2026)

Report: `eval/seed_stability_seed2.md`; method traps in `ABLATION_NOTES.md`
("Reseeding a generation"). Each arm had run once per question, so every quality
number was one draw. **21 of 25 questions scored 5/5/5 across all arms** and
contribute zero to every paired delta — the A-vs-C delta of -0.28 is exactly
(3-5)+(4-5)+(4-5)+(2-5) over h01/h02/h05/h06, ÷ 25. Four questions carry the
whole quality conclusion.

| view | A | B | C | A vs C Δrel [95% CI] | B vs C discordant |
|---|---|---|---|---|---|
| seed 1 | 23/25 | 24/25 | 25/25 | -0.28 [-0.60, -0.04] | 1 |
| seed 2 | 23/25 | **25/25** | 25/25 | -0.28 [-0.68, +0.00] | **0** |
| pooled | 23/25 | 24/25 | 25/25 | -0.28 [-0.60, -0.02] | 1 |

**A vs C reproduced exactly** (-0.28 three times; pooled CI still excludes zero);
**B vs C collapsed** to zero discordant pairs. Drift sits where the signal is — 0
flips in 6 control cells vs 25% of discordant cells; per-arm flips A 2/6, B 1/6,
C 0/6, six cells giving useless intervals, so the ordering is suggestive only.
**Arm A's retrieval is deterministic** (byte-identical chunk sets, unchanged
MRR@10 on all six), so h01's miss is a reproducible pipeline property, not a bad
draw. h01's 3 → 1 drop was a substring artifact, fixed Aug 2026 —
`_phrase_satisfied` now folds word separators.

Ablation context the seed qualifies: **the judge-run count changed the ranking
without changing a single answer.** At `--judge-runs 1` arm B led 25/25 to C's
24/25; at 3 runs C leads 25/25 to B's 24/25, every generation replayed from cache —
the arms are separated by less than the judge's own noise. Critical-error counts
were **unioned** in that pass, so they grow with the run count and compare only
between arms within one pass. And **h06's mechanism was confirmed by the second
seed, its verdict was not** — the reseeded arm-B answer states the same
chunk-granularity ceiling in the same terms yet scored EQUIVALENT/4 where the first
scored DIFFERENT/2. Cite h06 as a mechanism, never as a tally.

---

## Rerank A/B — the measurements behind the decision (COMPLETION_PLAN Phase 4)

Decision and the metric warning live in `CLAUDE.md`; full working in `HISTORY.md`.

Local retrieval-only timing, 3 queries, this machine:

| | q1 | q2 | q3 | mean |
|---|---|---|---|---|
| rerank ON | 29.0s | 39.0s | 23.8s | **30.6s** |
| rerank OFF | 0.1s | 11.6s | 0.1s | **4.0s** |

(q2's 11.6s with rerank off is the HyDE call, not the reranker.) Rerank is ~26.6s of
every query — consistent with the ablation's finding that retrieval is 70% of arm A's
wall clock, and Phase 3 later measured it costing ~40 of the 79 minutes the deliverable
groundedness gate spends, since `entail_claim` re-retrieves per claim.

Paired tuning-subset run (`--no-rerank`, separate `--cache-dir`, `--run-id norerank1`)
against Phase 2's `verify2`:

| | rerank ON | rerank OFF |
|---|---|---|
| EQUIVALENT | **14/15** | 13/15 |
| critical errors | **0** | 1 |
| recall@10 (pages) | 0.923 | 0.923 |
| MRR@10 | 0.705 | **0.885** |
| nDCG@10 | 0.745 | **0.847** |
| mean relevance | **4.87** | 4.60 |

12 of 15 questions score identically and the entire difference is **h04 alone**, 5 → 1
— one discordant pair at n=15, McNemar p = 1.000, so there is no statistical claim
here. The decision rests on the mechanism: chunk `[2,3,4]` of `Calculating Your Break
Even Point` is the **only** chunk containing both `7,200` and `522`; rerank put it at
rank 6, inside the window, and without rerank it left the top-10 entirely. That is
exactly what a cross-encoder is for, so one instance of it is worth ~26.6 s/query here.

The metric inversion, in full: MRR@10 and nDCG@10 both *improved* on the run that
produced the critical error; h04's own MRR went 0.33 → 1.00 while its answer broke,
because gold pages are chunk-shaped and matching is page-OVERLAP — no-rerank's rank-1
chunk `[1,2,3]` scores a perfect hit by sharing pages 2-3 with gold `[2,3,4]` while
containing neither number. `mrr_at_10` and `ndcg_at_10` are in
`eval/gate.py::DEFAULT_TOLERANCES`, so the gate can pass, and even reward, a retrieval
change that degrades answers.

---

## F07 — the deliverable groundedness verdict, in full (COMPLETION_PLAN Phase 3)

Run against the **checked-in** `deliverables/business_plan.md`, via
`run_groundedness_check` directly — never `compose_capstone.py`, whose `main()`
regenerates the plan before gating it. The plan's sha256 was asserted unchanged before
and after.

**89 claims, 0 ERROR, 38 SUPPORTED / 19 PARTIAL / 32 UNSUPPORTED. High-risk blocking
rate 27.4% (17 of 62) against a 5% threshold → GATE FAIL.** Zero errors matters: the
verification was complete, so this is a real verdict, not the mid-run CLI outage that
rule 2 exists to catch. Artifacts: `deliverables/{claims,entailment,groundedness_report}`.

The checker is sound (validation + the full claim breakdown are in `HISTORY.md`), but
the 17 split three ways and only the last is what anyone means by hallucination: **8
are the plan's own forward projections**, **7 are invented operational specifics**, and
**2 are unsourced real-world facts** ("Binghamton University has ~18,000 students";
"Starbucks loyalty drives 53% of US transactions").

So the honest reading is TWO results. The plan does carry unsourced factual assertions.
And **a 5% high-risk threshold is structurally unpassable for a document whose genre is
projection** — the gate was designed against RAG answers, where every claim should trace
to a chunk, then applied to a business plan, where most legitimately cannot. The
deliverable was submitted Apr 2026 and is not being rewritten; recorded rather than
fixed, which is what the plan's decision point allows.

Cost note: 90 CLI calls but **79 minutes**, because `entail_claim` runs a full
`hybrid_search` per claim — ~40 of the 79 minutes is the cross-encoder.

---

## What `citation_claim_support_avg` cannot see

It is REPORTED, never gated, and measures a different thing from
`citation_page_accuracy_avg` (attribution vs fabrication). Bluntly:

- **Only spans that carry a citation.** A false claim with no marker is invisible; an
  answer citing nothing scores `None`, not 0.0. This is attribution, not groundedness.
- **Evidence is the UNION of every chunk whose pages intersect the citation**, which is
  deliberately permissive — needed so adjacent chunks sharing a boundary page are not
  punished, but it means **page-level precision is not measured at all**. h06's ceiling
  (an answer that can only cite `pages 1-3` where the fact is on page 2) is exactly as
  invisible here as it is to `page_accuracy`. Only a finer chunk grid closes that.
- **Cross-chunk synthesis is scored unfairly:** a claim honestly assembled from two
  chunks but cited to one scores PARTIAL. This hits `synthesis` questions hardest, so
  the raw mean is not comparable between a synthesis-heavy and a lookup-heavy arm.
- **Quote verification is a fabrication guard, not a correctness guarantee.** Token
  recall ≥ `CITATION_QUOTE_MIN_TOKEN_RECALL` instead of exact substring is what stops
  docling's reordered text from failing correct citations; the price is that reordering
  a source's own words into a claim it does not make will pass. Negation and reversed
  causality are caught only by the model's judgement.
- **The LLM stage is same-family and uncalibrated.** There is no human-labelled
  citation-support ground truth in this project, so the metric's precision on its own
  flag set is unknown. Building a calibration set is the honest next step.
- **The number depends on `--support-runs` and on `support_scope`;** the gate prints
  `SKIP(incomparable)` rather than a delta when either differs. Never quote across them.
