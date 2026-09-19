# Project history — decisions that still constrain changes

Moved out of `CLAUDE.md` to keep the project memory light. Nothing here is a
pending action; every item is done. Kept because the *reason* behind each one
still constrains what a future change may do.

## Recent Changes (Weekend 4, July 2026 — design-review fixes)

A multi-agent design review (July 2026) confirmed 50 flaws; the top ten were fixed
in this batch. **A re-ingest is required** (`CHUNKER_VERSION` bumped 3 → 4 for the
new chunk-ID scheme). Fix summary, with the review's finding IDs:

All are fixed and covered by the fast suite; the code is the detail. Kept here
only for the constraint each one still imposes:

- **F03 per-source floor, not cap** (`retrieval.py`) — `apply_min_per_source`
  promotes to satisfy floors with priority eviction, from the full fused list, so
  it still works under a shallow rerank. It is a floor; do not reintroduce a cap.
- **Rerank latency** (`config.py`) — `RERANK_TOP_N` 50 → 30. 50 full-size chunks
  measured ~86s on this machine; the old "<2s" comment was wrong by ~40x.
  `RERANK_INPUT_CHAR_BUDGET` pre-truncates (the model cuts at 512 tokens anyway).
- **F13/F14 judge bugs** (`eval/run.py`) — `_judge_numeric` strips page references
  before extracting numbers ("see pages 30-32" must not match expected 32.5); digit-free
  answers are `FORMAT_FAIL`, wrong numbers `WRONG_EVIDENCE`, never `HALLUCINATION`.
- **F11 gate fail-closed** (`eval/gate.py`) — a metric the current run lost but
  the baseline carries is a FAIL, not a skip; absolute floors and the judge-outage
  check run baseline-independently so a stale baseline cannot mask a collapse.
- **F01/F02 chunk IDs** (`vectorstore.py`) — `{project}::{source}::{sha1(FULL
  text)[:16]}`, `::N` for true duplicates, uniqueness assert before upsert.
  Hashing a prefix collided; the same source in two projects now coexists.
- **F15 typed CLI errors** (`claude_bridge.py`) — `ClaudeCLIError`, not `sys.exit(1)`,
  so `chat` survives a failed turn. Plus `errors="replace"` decoding.
- **F24 hermetic CLI calls** — the subprocess runs in a neutral temp cwd so the
  CLI cannot auto-load this file (which contains the eval rubric) into every
  generation and judge call.
- **F05/F06 groundedness gate fail-closed** (`groundedness.py`) — ERROR entailments
  count as blocking, >10% ERROR fails, zero high-risk claims fails. Any currency/percent
  figure is high-risk by itself.
- **F09 proportional corpus packing** (`compose_capstone.py`) — per-source budget
  allocation; the old blind tail cut silently dropped alphabetically-last sources.
- **F25 `--doc` validation + empty-context guard** (`pipeline.py`) — never prompt
  the LLM with an empty context; it answers "not in the material" confidently.
- **F10 parseable citations** (`pipeline.py`, `prompts.py`, `citations.py`) —
  headers render `pages 3-5`, prompts pin `[source, page N]`, parser keeps a
  backward-compat pattern for the legacy bracketed-list shape.

---

## History (Weekends 1-3, April-May 2026) — decisions worth keeping

Narrative dropped; the decisions and their reasons are kept, because those still
constrain changes.

- **Retrieval (W1).** `all-MiniLM-L6-v2` (384-dim) → BGE-M3 (1024-dim, 8192
  tokens) — big quality win on technical material, and why a re-ingest is needed
  whenever the embedding model changes. BM25 added as a second channel because
  pure dense retrieval misses exact matches (acronyms, equations, identifiers),
  fused with RRF (rank-based, so no score normalization), then cross-encoder rerank.
- **Vector store (W1).** One-collection-per-document → a single `documents`
  collection with `source` as a metadata filter: query time O(1) in document count
  rather than O(n_docs × n_results). Singleton client + collection.
- **Parser (W1).** DOCX (python-docx) and XLSX (openpyxl) share the PDF chunk
  schema. DOCX flattens to ~3000-char synthetic "pages"; XLSX renders one synthetic
  page per worksheet, rows pipe-delimited, `data_only=True` for cached formulas.
- **Project scoping (W2).** Every chunk carries `project` so study domains coexist
  in one ChromaDB without leaking. All CLI commands accept `--project`.
- **Idempotency (W2).** Chunks carry `file_sha256`, `chunker_version`,
  `embedding_model`; `ingest` short-circuits when all three match. Bumping
  `CHUNKER_VERSION` or `EMBEDDING_MODEL` is the correct way to invalidate the
  cache — manual deletion is never needed.
- **HyDE (W2).** A 2-4 sentence hypothetical answer becomes a third retrieval
  channel. `should_use_hyde` skips short and lookup-style queries because HyDE
  actively hurts those shapes. One Sonnet call per qualifying query.
- **docling (W2).** Layout-aware PDF backend (tables as markdown, headings kept),
  PyMuPDF as fallback. A markdown heading is a hard chunk boundary, but only once
  the running chunk reaches `MIN_CHUNK_CHARS` — without that floor the chunker
  fragmented short sub-sections into useless tiny chunks. Corpus 54 → 121 chunks.
- **OCR (W2).** Per-page easyocr fallback under `OCR_MIN_PAGE_CHARS`, so only empty
  pages pay. The current corpus never triggers it.
- **Eval contract (W3)** — still defines how quality is measured: evidence-only
  judging (judges see retrieved evidence, not just expected-vs-actual, so
  paraphrase similarity cannot mask grounding errors); strict 5-axis JSON schema
  with a controlled critical-error vocabulary; multi-run median with per-axis
  flip-rate; per-type judges (numeric/negative/page_lookup rule-based,
  qa/synthesis LLM); MRR@10 + nDCG@10; citation parsing and validation; trace
  persistence; and the oracle harness that attributes a failure to retrieval vs
  generation by re-running with gold-only chunks.
- **Groundedness gate (W3).** `groundedness.py` entails each atomic claim against
  top-3 chunks; `compose_capstone.py` blocks export above a 5% high-risk
  unsupported rate. `--force-export` bypasses.
- **Holdout discipline (W3).** 10 of 25 hard questions are holdout, 2 per type.
  Iterate with `--holdout tuning`, freeze, run holdout once before quoting.
- **Verifier temperature (W3).** Judges and entailment pass `temperature=0.0`. The
  CLI ignores it (no such flag), so it documents intent and lands in traces; an SDK
  port honours it with no caller changes. **This last clause was wrong** — see
  CLAUDE.md's SDK section: `claude-opus-5` / `claude-sonnet-5` reject `temperature`
  with a 400, so the SDK path drops it. Neither backend applies it.

Superseded since: the Weekend-3 eval numbers, the bootstrapped calibration set,
and the then-current baseline. See the ablation sections above.

---

## Task 20: the withheld freeze, the judge fixed in both directions, freeze2 taken (Aug 2026)

The freeze attempt (`freeze1`, full 25, `--judge-runs 3 --judge-evidence own`) executed
cleanly — 24/25 EQUIVALENT, medians 5/5/5, holdout 10/10 with zero critical errors — but
`eval/gate.py` exited 1 on two tuning-question errors: h01 `WRONG_EVIDENCE`, h07
`CITATION_WRONG`. The freeze was withheld rather than taken, for reasons that turned out
to be three distinct defects.

**h07 was a verified false positive.** Nine-agent adjudication, unanimous, against
verbatim chunk text: the `Briefing Doc` `[4,5]` chunk literally contains
`Break-even point = Fixed Costs / Gross Margin %` plus its worked example, and consists
of numbered FAQ items, so both the citation and the word "FAQ" were correct;
`[Calculating Your Break Even Point, pages 1-3, 4-5]` parses fine (`validate_citations`
→ `valid: true`) and its page set is exactly the union of the two retrieved chunks. The
majority itself was an artifact of label-only vote counting: run 1 quoted the
FAQ-formula span, run 2 quoted a citation three paragraphs away — neither span accused
twice, yet `counts['CITATION_WRONG'] == 2` carried it.

**`_judge_page_lookup` was wrong in BOTH directions**, measured by running the real code
against planted answers:

| answer | rule output (pre-fix) |
|---|---|
| freeze1's honest abstention | `1/1/1 + WRONG_EVIDENCE` |
| fabrication, wrong name *and* page | `1/1/1 + WRONG_EVIDENCE` — byte-identical |
| fabrication, RIGHT name, fabricated page 3 | `3/3/3 + NONE` — no error at all |

`must_contain` is a content-PRESENCE proxy, so all-miss is the union of {asserted
something wrong} and {asserted nothing} — F13 (`_judge_numeric`) unfixed one judge over.
And the false negative was the single defect a page_lookup question exists to catch.
Compounding it, `tools/probe_judge.py` contained zero occurrences of `page_lookup`,
`_judge_numeric` or `_judge_negative`: the rule judges deciding 15 of 25 questions had
never been defect-probed.

**Fix order was probe-first, and the probe went red before it went green.** The extended
probe (rule judges + scripted-run vote aggregation, all offline via `--rules-only`) was
run against the UNFIXED judge: red on exactly the three defect cases, green on all 14
existing behaviors. Then three code-only fixes (the rubric text never moved —
`judge_prompt_hash ba29d7420a62` byte-identical throughout):

1. All-miss splits on `_ABSTENTION_RE`: context-lack wording → `FORMAT_FAIL` 1/1/1,
   otherwise `WRONG_EVIDENCE` 1/1/1. The detector anchors on the CONTEXT lacking the
   fact, never first-person inability, because norerank-h04's answer hedges "I can't
   pinpoint a single page number" around a confidently wrong worked example and must
   keep firing WRONG_EVIDENCE — the case that forbids a naive hedge-word detector. It
   was designed on tuning answers only (freeze1/verify1/verify2 h01, norerank h04).
2. The partial branch accuses a wrong page: missed `page N` assertion + non-abstaining
   answer + cited pages → `CITATION_WRONG` 2/2/2. Chunk-grain citations satisfy
   subset-first, so h06-style range citations cannot trip it.
3. `_judge_llm_aggregated` votes span-aware (`_max_same_span_votes`): a label survives
   only if one span collects the majority, spans being overlapping quote intervals in
   the candidate; empty-quote votes are wildcards so legacy `per_run` rows re-aggregate
   byte-identically.

Blast-radius replay over 29 stored result files (13 rule-decided page_lookup cells, 174
per_run aggregations): exactly 3 cells change — freeze1 h01 and its seed2 twin
(`WRONG_EVIDENCE`→`FORMAT_FAIL`) and freeze1 h07 (cleared). No stored honest answer
trips the new wrong-page branch. 74 fast tests green (3 new ones pin the behavior).
`judge_code_hash` 6abaef139a17 → 587f0fb8e468.

**freeze2** replayed freeze1's cached answers (generation and retrieval byte-identical)
and judged fresh: 24/25 EQUIVALENT, 0 errors, medians 5/5/5, flip-rate 0.040, citation
page-accuracy 0.990, critical errors `FORMAT_FAIL=1` (h01, correctly named, still
DIFFERENT with `MRR=0.0`), holdout 10/10 clean. Exactly two cells differ from freeze1 —
the two the fixes were designed to move. Mid-run the CLI hit a session limit at h19-h21;
the checkpoint kept 22 rows and `--resume` retried the three ERROR rows after the reset.
Gate vs the judgefix baseline: PASS, no new critical errors; `eval/baseline.json`
regenerated from freeze2 (prior baseline in `eval/.backup_freeze/baseline_prefreeze.json`,
freeze1's results in `.backup_freeze/results_hard_freeze1.*`); gate vs the new baseline:
PASS with zero warnings.

The second holdout exposure was sanctioned explicitly and is defensible because every
fix was designed on tuning questions and planted probes; holdout output was never read
during design.

## Phase 4 rerank A/B — full working (Aug 2026)

Decision and headline table are in CLAUDE.md. What is kept here is the working.

**Baseline choice was load-bearing.** The comparison is against `verify2`, NOT
`verify1`: verify1 was scored under the pre-fix `_phrase_satisfied`, so pairing against
it would confound the rerank effect with the judge change (h04 aside, h01 alone would
swing DIFFERENT→PARTIAL for reasons unrelated to retrieval). verify2 predates
`judge_code_hash`, so comparability was established by replaying its stored answers
through the current rule-based judges — 6 of 6 replayable questions reproduced their
stored verdict exactly, and both files carry `judge_prompt_hash ba29d7420a62`. From
`norerank1` onward the stamp makes this mechanical.

**Per-question:** 12 of 15 identical. h03 groundedness −1 and h18 groundedness +1
cancel. h04 5 → 1 is the whole aggregate delta (−0.267 × 15 = −4.0, exactly h04).

**h04 mechanism, verified against the corpus, not inferred from the answers.** The
three chunks of `Calculating Your Break Even Point` are `[1,2,3]`, `[2,3,4]`, `[4,5]`;
only `[2,3,4]` contains `7,200` and `522`. Rerank ON ranked it 6th — inside the top-10
— and the answer quoted the figures (EQUIVALENT). Rerank OFF dropped it from the window
entirely; the answer could only describe the startup-cost scenario and the per-item
margin, so both `must_contain` phrases missed and `_judge_page_lookup` returned 1/1/1 +
WRONG_EVIDENCE. Note the no-rerank window also spent two slots on
`Student "How to Earn an A"` and two on `How To Understand Your Customers`.

**Why MRR rose while quality fell:** gold for h04 is pages `[2,3,4]` and matching is
page-overlap, so no-rerank's rank-1 chunk `[1,2,3]` counts as a hit at rank 1 (shares
pages 2-3) despite holding neither number. The label rewards page adjacency; the answer
needs fact presence.

**A/B safety:** `use_rerank` is inside `ArmAHybridRAG.config_hash()` — verified
`e8db6aa9bd3e` (ON) vs `3156fa4b1a33` (OFF) — so the content-addressed answer cache
cannot replay reranked answers into a no-rerank run, the failure that made a separate
`--cache-dir` load-bearing for seed 2. The MD report also carries a `RERANK DISABLED`
banner so such a run cannot be misread as a default one.

---

## Phase 3 / F07 groundedness on the deliverable — full working (Aug 2026)

Verdict and headline numbers are in CLAUDE.md. The breakdown of the 17 high-risk
blocking claims:

- **8 are the plan's own forward projections** — net margin 18.7 → 32.7%, owner's equity
  $2,000 → $100,000 by 2030, mobile ordering +8-12% by 2028, COGS −1.5pp saving ~$11,000,
  break-even rising to ~$14,800/month, data completeness >90% by 2027.
- **7 are invented operational specifics** — $5.50-7.00 single-origin pricing, Friday
  open-mic with a $3 cover, $25 monthly tastings, POs over $500 needing GM approval,
  AES-256 / TLS 1.3, a $50 POS-compliance bonus, GM authority to roll back automation
  below 4.0/5.0 CSAT.
- **2 are unsourced real-world facts** — "Binghamton University has approximately 18,000
  students" and "Starbucks's loyalty program drives 53% of its US transactions". These
  are the genuine hallucination finding.

The checker was validated before the FAIL was accepted: SUPPORTED rationales quote real
corpus content (revenue `720,000 → 648,000 → 583,200` off the `Hist_2023_2025` sheet)
and UNSUPPORTED ones are specific ("the evidence never mentions a grandfather, the
café's founder, or Binghamton, New York"). `n_error = 0` is what makes the verdict
trustworthy — a quota outage would have produced an identical-looking FAIL via rule 2.

**Cost:** 90 CLI calls but 79 minutes, because `entail_claim` is called with
`retrieved_chunks=None` and so runs a full `hybrid_search` per claim, cross-encoder
included — roughly 40 of the 79 minutes.

---

## The six "carried-over defects" — full account (Aug 2026, moved from CLAUDE.md)

`CITATION_WRONG` h02/h06/h17 + `HALLUCINATION` h03/h05/h07, adjudicated against the
actual chunk text: **zero survived.** Two flags were provably founded on text the
answer never contained — h07 run2 justified HALLUCINATION with "no $7,200/$2,800/$522
figures given in evidence" when those strings occur **zero** times in the candidate and
all three in the *reference* (it graded the wrong document); h17 run0 said the
"toxicity" tip was cited to pages 19-21 when the bullet already ends `[…, pages 14-17]`.
All six sat at exactly 2-of-3, never unanimous, so one bad vote was decisive.

Four judge fixes, **none in the generator**:

- **The label vocabulary had no definitions** — a bare set literal, so HALLUCINATION
  became a bucket for "went beyond the reference". Each label is now defined, with
  "a matter of degree belongs on the axes, not in a label".
- **The judge was never told chunks span page ranges**, so it scored citations against
  the *reference's* pages instead of the EVIDENCE headers, penalising precision the
  chunking cannot provide (h02, h06). The rubric now says adjacent chunks share a
  boundary page by construction and the reference is not the citation standard.
- **`JUDGE_SYSTEM` said "penalize verbosity, unsupported claims"** in one breath, and
  rationales cite that clause by name while routing style into the grounding axes. Now
  "the reference is a minimal sufficient answer, NOT a ceiling; length alone is never
  a critical error".
- **Every vote must quote the span it accuses** (`{"label","quote"}`);
  `_quote_is_in_candidate` drops votes whose quote is absent from the answer. Fails
  **open** on an empty quote so pre-change `per_run` rows re-aggregate byte-identically.

Full re-judge (same cached answers, `--judge-runs 3 --judge-evidence own`): **6 → 0
blocking errors, none new**, every clearance *unanimous* (3/3 NONE), so the rubric did
the work, not the vote filter. Axis means +0.24 rel / +0.44 gnd / +0.68 cit; verdicts
unchanged 24/25; retrieval byte-identical. h05/h06 are **holdout**, were excluded from
the fix design, and cleared without ever being looked at.

Also: rationales no longer truncate at 300 chars (`_MAX_RATIONALE_CHARS`) — h07's was
cut mid-word at "and several oth", destroying the record of *why* it flagged; and the
envelope now carries `judge_prompt_hash` / `qa_prompt_hash` (joined Aug 2026 by
`judge_code_hash`), with `eval/gate.py` warning, never failing, on drift.

---

## Migration Note (weekend 1)

If you pulled the weekend-1 changes and the old `data/chromadb/` folder still exists,
it's safe to delete. The pipeline reads/writes `data/chroma_v2/` and ignores the old
path; on re-ingest BGE-M3 populates `chroma_v2/` and the old folder is dead weight.

```
Remove-Item -Recurse -Force data\chromadb
```

---
