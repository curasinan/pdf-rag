# PDF RAG Study Tool

A local RAG pipeline for studying from PDFs that exceed Claude's context window. Ingest PDFs (and DOCX) into a vector store, then query, summarize, teach, quiz, or chat against the material via the Claude Code CLI.

This file is the project memory for Claude Code. Read it before making non-trivial changes.

---

## Architecture

Single-collection ChromaDB (1024-dim BGE-M3 vectors) plus an in-memory BM25 keyword index, fused via Reciprocal Rank Fusion, then reranked with a cross-encoder. Generation goes through the Claude Code CLI (uses plan limits, not the paid API).

Per-query flow:

1. Embed the query with BGE-M3.
2. Pull `RETRIEVAL_CANDIDATES` (50) from ChromaDB by cosine distance.
3. Pull `RETRIEVAL_CANDIDATES` (50) from BM25 by keyword score.
4. Reciprocal Rank Fusion (k=60) merges both lists into one ranking.
5. Top `RERANK_TOP_N` (30) go to the BAAI/bge-reranker-v2-m3 cross-encoder.
6. Top `DEFAULT_TOP_K` (10) chunks become the context block for the LLM.

All chunks live in one collection (`documents`), with `source` as a metadata field. Per-document scoping uses ChromaDB's `where={"source": ...}` filter, so query latency does not scale with document count.

---

## Module Reference

| File | Purpose |
|---|---|
| `rag.py` | CLI entry point. Subcommands: `ingest`, `query`, `summarize`, `analyze`, `teach`, `quiz`, `chat`, `list`, `projects`, `delete`. Top-level `--verbose` / `-v` flag enables DEBUG logging. |
| `pipeline.py` | Orchestrates each command. Calls retrieval + formats context + invokes prompts. Imports `_call_claude` from `claude_bridge`. Idempotent `ingest` short-circuits on cache hit. |
| `claude_bridge.py` | Single point for every Claude call. Two backends behind `config.BRIDGE_BACKEND`: **`cli`** (default — `claude -p`, plan limits, no API charges) and **`sdk`** (Anthropic SDK, METERED billing, double-opt-in). `call_claude_agentic` is CLI-only unconditionally. |
| `hyde.py` | HyDE query rewriting. `generate_hypothetical_answer` (Sonnet) writes a short fake answer whose embedding is a third retrieval channel; `should_use_hyde` skips short / lookup queries. |
| `retrieval.py` | Hybrid search: dense + (optional HyDE-dense) + BM25 + RRF + cross-encoder rerank + per-source quota. The single function callers should use is `hybrid_search`. |
| `embeddings.py` | BGE-M3 loader and `embed_texts`. Vectors are L2-normalized so cosine == dot product. |
| `vectorstore.py` | Single-collection ChromaDB, singleton client + collection. Where filters compose source / project predicates. `get_all_chunks` powers BM25 indexing. |
| `bm25.py` | rank_bm25 index over ChromaDB chunks, pickled to `data/bm25.pkl` with a (count, last_id) signature. `invalidate()` after ingest/delete; filters by source / project after scoring. |
| `reranker.py` | Lazy-loaded cross-encoder. Score (query, candidate) pairs jointly. |
| `pdf_parser.py` | Document parser. PDF via docling (tables-as-markdown, headings, layout) with PyMuPDF fallback; DOCX via python-docx; XLSX via openpyxl. Section-aware chunker honors heading boundaries once the chunk reaches `MIN_CHUNK_CHARS`. Per-page easyocr fallback under `OCR_MIN_PAGE_CHARS`. `file_sha256` helper. |
| `prompts.py` | All system + user prompt templates including `HYDE_SYSTEM` / `HYDE_USER`. Edit here, not in `pipeline.py`. |
| `config.py` | Single source of truth for tunables. Models, paths, retrieval constants, project default, chunker version, HyDE / OCR / docling toggles. |
| `logging_setup.py` | `setup_logging(verbose)` wires console + rotating file logging. Called once from `rag.py` / `batch_ingest.py`. |
| `batch_ingest.py` | Walks a folder recursively, ingesting every `.pdf` / `.docx` / `.xlsx`. Reports `Ingested` vs `Cached`; `--project` scopes it. |
| `migrate_phase0.py` | One-shot migration: assigns `project="capstone"` to pre-project chunks. Idempotent; `--commit` vs dry-run. |
| `eval/run.py` | Eval harness. Default = easy set; `--hard` the expanded set; `--holdout {all,tuning,holdout}` subsets it. Evidence-only 5-axis JSON judges, multi-run median, MRR/nDCG, citation validation, RagTrace per question. |
| `eval/questions.json` | Easy regression set, source-level recall only. |
| `eval/questions_hard.json` | Hard set: `must_cite_sources` (per-source pages), `must_contain`, `expected_numbers`, `holdout: bool`. 25 questions (10 holdout, 15 tuning). |
| `eval/gate.py` | Regression gate. `python eval/gate.py --current eval/results_hard.json` exits 0/1. Tracks recall, MRR, nDCG, judge medians, citation accuracy + critical-error rules. |
| `eval/baseline.json` | Snapshot the gate compares against. FROZEN Aug 2026 from run `freeze2` (`--arm A --judge-runs 3 --judge-evidence own`, span-aware judge; see the Phase-6 section). Prior copies: `.backup_freeze/baseline_prefreeze.json` (judgefix), `.backup_judgefix/`, `eval/baseline_legacy.json`. |
| `eval/calibration.json` | 25 calibration anchors with bootstrapped human labels (`bootstrap_method="prior_verdict_mapping"`). |
| `eval/calibrate.py` | Runs the judge N times per anchor; reports per-axis accuracy / flip-rate / confusion. |
| `eval/bootstrap_calibration.py` | One-shot: rebuilds `calibration.json` from a prior eval results file. |
| `eval/oracle.py` | Oracle-context harness. Re-runs failures with gold-only chunks; classifies retrieval vs generation failure. |
| `eval/arms.py` | Answer producers — the one seam where arms differ. `Production` + `ArmAHybridRAG` / `ArmBFullContext` / `ArmCAgenticFiles` + `make_producer`. Downstream of `produce()` is arm-agnostic. |
| `tools/build_mirror.py` | Builds arm C's plain-text corpus mirror from `pdf_parser.extract_pages` (the extraction arm A ingests). Asserts every stored chunk's text is present; refuses OS-redirected paths. |
| `tools/probe_agentic.py` | Arm C pre-flight: envelope shape, sandbox leak, memory leak, citation parseability. **Plain terminal only.** |
| `tools/diagnose_agentic_auth.py` | Bisects CLI auth failures (API key vs flags vs no login). Found the `ANTHROPIC_API_KEY` billing trap. |
| `tools/probe_citation_support.py` | Plants a clean / miscited / fabricated-page citation and asserts the last two are caught. Run after ANY support-prompt edit, and bump `CITATION_SUPPORT_PROMPT_VERSION`. |
| `tools/probe_judge.py` | Plants defects at EVERY judge and asserts they are caught: rule judges (page_lookup both directions, numeric F13, negative F14), span-aware vote aggregation via scripted runs, plus the original clean/fabricated/miscited LLM plants. `--rules-only` skips the LLM section (no CLI calls). Run after ANY judge edit — rubric text or Python logic. Exits 0/1. |
| `tools/scan_leakage.py` | Post-hoc arm-C leakage check: verbatim 8-gram overlap with `expected_answer`, arms A/B as controls. Result: C **below** both controls, no leak. |
| `tools/audit_gold_pages.py` | Checks every gold page label against the source documents. A screening tool — it flags generic-word and decoy hits too, so read it with judgement. |
| `eval/ablation_report.py` | Paired arm comparison: exact McNemar + Holm, paired bootstrap, simulated MDE, cost/latency table. No LLM calls. |
| `eval/seed_stability.py` | Second-seed analysis: drift by stratum, exact binomial CIs, arm-A retrieval determinism, paired stats under seed1 / seed2 / pooled. No LLM calls. |
| `eval/cache.py` | `AnswerCache` (content-addressed; never caches errors) + `Checkpoint` (per-question JSONL so `--resume` survives a session limit; ERROR rows retried, not inherited). |
| `eval/gold.py` | Single owner of gold-passage resolution. `resolve_source` (normalization-insensitive) + `gold_chunks_for_question` (raises `GoldSourceMissing`, never `[]`). |
| `groundedness.py` | Claim-level entailment for `compose_capstone.py`. `extract_claims` → `entail_claim` (top-3 evidence) → `run_groundedness_check` (writes `claims.json`, `entailment.json`, `groundedness_report.md`). |
| `tracing.py` | `RagTrace` dataclass + `persist_trace`. One JSON per query under `data/traces/{run_id}/`. |
| `citations.py` | `parse_citations` (multi-pattern regex; each entry carries `spans` for every occurrence) + `citation_occurrences` + `validate_citations` (existence + page match — a FABRICATION check, not an attribution one). |
| `citation_support.py` | Claim-to-citation support: attribute each occurrence to the span it terminates, resolve the chunk it names, ask whether that chunk supports the claim. The adjudicator is injected, so every deterministic stage tests without an LLM. |
| `eval/backfill_citation_support.py` | Adds `citation_claim_support` to existing results from the stored answers — no generation re-run. Refuses to write when the corpus signature changed. |
| `eval/recompute_citation_validation.py` | Recomputes `citation_validation` in place after a parsing or source-matching change, printing the before/after delta. No LLM calls. |
| `eval/citation_support_report.py` | Cross-arm claim-support view: resolution grades, mean score per grade, and the arm-inversion guard. No LLM calls. |
| `HISTORY.md` | Weekend 1-4 changelogs, moved out of this file. Done work; kept for the constraints each decision still imposes. |
| `EVAL_NOTES.md` | Eval + judge deep detail, moved out of this file: baseline lineage, the six-defect clearance, the freeze mechanics, `judge_code_hash` traps, seed-2 tables, rerank A/B tables, F07 in full, claim-support blind spots. Read before editing `eval/run.py` / `eval/gate.py` or quoting a metric. |
| `ABLATION_NOTES.md` | Build traps from the finished ablation, moved out of this file to keep it light. Read before re-running or extending the study. |
| `ABLATION_WRITEUP.md` | The ablation study's written report: method, paired statistics, threats, conclusion. The shareable deliverable; `eval/ablation_report_corpus.md` holds the generated tables. |
| `compose_capstone.py` | One-shot deliverable generator. Runs G2 groundedness gate between plan generation and DOCX/PDF/PPTX/XLSX export. `--force-export` bypasses the gate. |
| `tests/test_smoke.py` | pytest smoke suite (74 fast tests). `pytest -m "not slow"` for fast runs; `pytest -m slow` runs the full hard eval + regression gate. |

Data layout under `data/`:

- `chroma_v2/` — current ChromaDB persistent dir (1024-dim BGE-M3 vectors, 121 chunks across 24 capstone docs after Weekend-2 docling re-ingest).
- `chromadb/` — legacy 384-dim MiniLM vectors. Safe to delete.
- `bm25.pkl` — pickled BM25 index. Auto-rebuilt on signature mismatch.
- `logs/rag.log` — rotating log file (5 MB × 3 backups). Always at DEBUG level regardless of `--verbose`.

---

## Traps that still bite (full set: `ABLATION_NOTES.md`)

The three-arm ablation is finished (`ABLATION_WRITEUP.md`). Its build notes moved to
`ABLATION_NOTES.md` — read that before re-running or extending it. What stays here is
what affects ordinary work:

- **Billing trap.** The user-scope environment holds a real 108-char `sk-ant-api03-…`
  key, and the CLI puts `ANTHROPIC_API_KEY` *ahead* of subscription OAuth in `-p` mode,
  so every call would be metered API billing — violating this project's "plan limits,
  not the paid API" contract. `claude_bridge._plan_auth_env()` strips it from every
  subprocess; escape hatch `PDFRAG_ALLOW_API_KEY=1`. A `claude` subprocess spawned
  inside a Claude Code session also cannot authenticate until the CLI has been logged
  in from a plain terminal.
- **Token accounting.** `usage.input_tokens` reads near-zero when a prompt is
  cache-served (measured **1** against a true **44,086**). Always sum
  `input + cache_read + cache_creation` — `claude_bridge.total_input_tokens`.
- **Judge evidence policy moves the metric more than the architecture does.** Same
  cached answers scored 1/3–2/3 EQUIVALENT and groundedness 1, 2 or 4 depending only on
  `--judge-evidence`. Use **`corpus` for any cross-arm comparison** (label-independent,
  byte-identical across arms); **`own` only for the arm-A baseline**, because it
  reproduces the faithfulness semantics `eval/baseline.json` is built on; **`gold` for
  neither** — it punishes an arm that correctly reads beyond the chunk-shaped label.
- **Gold page sets are chunk-shaped, not fact-shaped.** They record where arm A's
  retriever found an answer, not where the fact is — invisible to arm A, punishing to
  anything citing a precise page. Six labels corrected (h02, h04, h05, h12, h14, h15);
  `tools/audit_gold_pages.py` screens the rest but also flags generic words and decoys.
- **Source names resolve normalization-insensitively, twice over.** `5 KPIs …Café…` is
  stored NFD and labelled NFC, which silently returned **zero** gold chunks for four
  entries (`eval/gold.py`, now raises `GoldSourceMissing`). Separately, stored names
  carry typographic punctuation (`Franchise’s`, `“How to Earn an A”`) that a model
  retypes in ASCII; `citations._normalize_source` folds both (Aug 2026, +0.02 on
  `citation_page_accuracy_avg` across all three arms).
- **`results_stem()` owns output naming.** Non-A arms get their own stem, `--only`
  forces `_partial` so a pilot can't be read as a complete run, and `--out-suffix`
  separates repeat seeds. Every clause exists because two runs once shared a file.
- **Checkpointing + answer cache** (`eval/cache.py`). Per-question JSONL, so a session
  limit does not lose the run; `--resume` skips completed questions but **ERROR rows
  are retried, not inherited**, and errored productions are never cached.
  `SessionLimitError` aborts with resume instructions rather than scoring
  `"[generation failed]"` as an answer. Classification reads **stdout as well as
  stderr** — the CLI writes `Not logged in` to stdout with empty stderr.

## ABLATION RESULT (full 25 questions x 3 arms, run id `full1`, July 2026)

Narrative report: `ABLATION_WRITEUP.md`. Tables: `eval/ablation_report_corpus.md`
/ `ablation_results_corpus.json`, from the `--judge-runs 3 --judge-evidence
corpus` pass; the single-run pass is kept as `*_corpus_jr1.*`.

| arm | EQUIV | rel mean | cite prec | judge flip | wall s/q | in-tok/q | $/correct |
|---|---|---|---|---|---|---|---|
| A hybrid RAG | 23/25 | 4.68 | 0.96 | **0.167** | **57.6** | 41,172 | 0.229 |
| B whole corpus | 24/25 | 4.80 | 0.96 | 0.094 | 19.1 | **132,358** | **1.237** |
| C agentic files | **25/25** | **4.96** | **0.98** | **0.031** | 27.4 | 33,346 | **0.154** |

`cite prec` above is as-published. A later source-matching fix (typographic
punctuation in stored names) raised it to 0.984 / 0.987 / 0.995 — ordering unchanged.
It is a FABRICATION check; the attribution check added beside it scores the same
answers 0.923 / 0.906 / 0.871 (arm C on `corpus_only` scope, not comparable).

**Arm A is dominated** — slowest, pricier per correct answer than C, last on every
quality measure. Retrieval (chiefly the CPU cross-encoder) is 33-56s of its 57.6s;
generation is comparable across arms, so the component whose purpose is efficiency
is the bottleneck. Arm B buys its score with 3.2x the tokens and 5.6x the cost.

**No quality gap is separable.** All pairwise McNemar p = 1.000 after Holm (1-2
discordant pairs); simulated **MDE is 30 percentage points**, so this design can
neither separate the arms nor establish equivalence. The one exception to report
rather than bury: the paired bootstrap on mean relevance for A vs C gives -0.28
CI [-0.60, -0.04], excluding zero where McNemar does not — and the second seed
reproduced it at exactly -0.28, which is the strongest support it has.

**The judge-run count changed the ranking without changing a single answer.** At
`--judge-runs 1` arm B led 25/25 to C's 24/25; at 3 runs C leads 25/25 to B's
24/25, every generation replayed from cache — the arms are separated by less than
the judge's own noise. Critical-error counts are **unioned** in this pass, so they
grow with the run count and compare only between arms within one pass.

**Both of arm A's losses are architectural, not tuning.** **h01** — retrieval never
surfaced the answer (gold page 8; top-10 held chunks `[1,2,3]`/`[4,5,6]` of the right
document plus unrelated sources, `MRR=0.0`); arms B and C both answered it, and it
survives every Weekend-4 retrieval fix. **h06** — retrieval *succeeded* (`MRR=1.0`)
but the answer could only cite `pages 1-3`, the merged chunk, instead of page 2:
chunking destroys page-level citation precision. **h06's mechanism was confirmed by
the second seed, its verdict was not** — the reseeded arm-B answer states the same
ceiling in the same terms yet scored EQUIVALENT/4 where the first scored DIFFERENT/2.
Cite h06 as a mechanism, never as a tally.

**Threats to validity:** n=25 with a 30pp MDE; one generation run per arm on 19 of 25
questions (the 6 `page_lookup` ones, carrying all the paired signal, were reseeded —
next section); **arm B only exists because the 286K-char corpus fits in context**, so
above ~200K tokens that arm disappears and the comparison is vacuous; arm C's system
prompt necessarily includes Claude Code's agent scaffolding; arm B's prompt carries a
completeness preamble; arm C gets an `_INDEX.md` affordance; judges are same-family as
the generator.

---

## SECOND GENERATION SEED (Aug 2026) — what replicated and what didn't

Report: `eval/seed_stability_seed2.md`; full table + judge-noise context in
`EVAL_NOTES.md`; method traps in `ABLATION_NOTES.md` ("Reseeding a generation").
Headline: **A vs C reproduced exactly** (Δrel -0.28 in seed 1, seed 2, and pooled;
pooled CI [-0.60, -0.02] still excludes zero); **B vs C collapsed** to zero
discordant pairs. 21 of 25 questions score 5/5/5 in every arm — four questions carry
the whole quality conclusion. **Arm A's retrieval is deterministic** (byte-identical
chunk sets both seeds), so h01's miss is a reproducible pipeline property, not a bad
draw. Cite h06 as a mechanism, never as a tally — its verdict flipped on reseed while
its mechanism held.

---

## Recent Changes (post-ablation, Aug 2026 — baseline + judge aggregation)

Detail in `EVAL_NOTES.md`. `eval/baseline.json` regenerated onto the current schema
(legacy kept as `eval/baseline_legacy.json`; it silently SKIPped five of six tracked
metrics). Critical errors became **MAJORITY-voted** across judge runs instead of
unioned — one dissenting run could brand an answer with a gate-blocking error, and the
false-positive count grew with `--judge-runs` by construction; published ablation
error counts predate this. The regression gate **blocks on NEW critical errors only**;
carried-over ones print without blocking; passing no baseline restores absolute
behaviour.

---

## The six "carried-over defects" were the rubric, not the system (Aug 2026)

Full account: `HISTORY.md`; summary: `EVAL_NOTES.md`. All six (`CITATION_WRONG`
h02/h06/h17, `HALLUCINATION` h03/h05/h07) were judge false positives — zero survived
adjudication against the chunk text, two were founded on text the answer never
contained, and all six sat at exactly 2-of-3. Four fixes, all in the judge, none in
the generator; re-judge on the same cached answers: **6 → 0 blocking errors, none
new**, verdicts unchanged 24/25. h05/h06 are holdout and cleared without being read.

Two rules that still bind:

- **Run `python tools/probe_judge.py` after any judge edit — rubric text or Python
  logic.** A change that clears errors looks identical to one that blinded the judge
  until you plant defects. `--rules-only` is free (no CLI calls).
- **`_quote_is_in_candidate` fails OPEN on an empty quote**, so pre-change `per_run`
  rows re-aggregate byte-identically. Never tighten it to fail-closed.

---

## The clearance holds under fresh generation (Aug 2026, COMPLETION_PLAN Phase 2)

Fresh generations (separate `--cache-dir`), fresh judging, tuning subset: **14/15
EQUIVALENT + 1 PARTIAL (h01), medians 5/5/5, zero critical errors** —
verdict-for-verdict identical to `judgefix`, retrieval byte-identical on all 15.
`eval/results_hard_verify{1,2}.{json,md}`; full working in `EVAL_NOTES.md`. It took
two passes: `verify1` failed on ONE HYPHEN (`table-turn` vs `table turn` — an
orthography test, not a content test), so `_phrase_satisfied` now retries with word
separators folded; replayed over 193 stored phrase-checks it changes exactly one cell,
regresses none, and never touches holdout. h01 stays PARTIAL 3/3/3 with `page 8`
unsatisfied, `pages_full: false`, `MRR=0.0` — the failure is named, not hidden.

---

## Phase 6 freeze TAKEN (Aug 2026) — `eval/baseline.json` = run `freeze2`

The first attempt (`freeze1`) was withheld: its sole gate blocker (h07
`CITATION_WRONG`) was a verified false positive manufactured by label-only vote
counting, and the investigation exposed `_judge_page_lookup` as wrong in BOTH
directions — an honest abstention scored byte-identical to a fabrication, while
right-entity/fabricated-page (the one defect a page_lookup question exists to
catch) produced no error at all. Three code-only judge fixes followed, probe-first,
designed on TUNING questions (h01, h04, h07) and planted probes, never holdout
output: an abstention-vs-assertion split in the all-miss branch (`FORMAT_FAIL` vs
`WRONG_EVIDENCE`), a wrong-page `CITATION_WRONG` branch, and span-aware
critical-error voting. Judge mechanics + blast radius: `EVAL_NOTES.md`; full
account, planted-answer tables and the h07 adjudication: `HISTORY.md` ("Task 20").

**The frozen numbers** (run `freeze2`, full 25, `--judge-runs 3
--judge-evidence own`, CLI backend, rerank ON; answers replayed byte-identical
from freeze1's cache, so the delta is the judge fix and nothing else):

- 24/25 EQUIVALENT, 1 DIFFERENT (h01), 0 generation errors
- medians 5/5/5, relevance flip-rate 0.040
- recall@10 source 100% / pages 95.2%, MRR@10 0.746, nDCG@10 0.771
- citation page-accuracy 0.990; claim-support 0.916 (reported, not gated)
- critical errors: `FORMAT_FAIL=1` (h01) — nothing gate-tracked
- **holdout: 10/10 EQUIVALENT, zero critical errors**
- vs freeze1, exactly two cells changed: h01 `WRONG_EVIDENCE`→`FORMAT_FAIL`
  (label corrected, failure NOT cleared: still DIFFERENT 1/1/1, `MRR=0.0`,
  `pages_full: false`) and h07's error cleared (EQUIVALENT 5, `NONE`)
- gate vs the judgefix baseline: **PASS**, no new critical errors; baseline
  then regenerated from freeze2 → gate PASS with **zero warnings** (both
  hashes now covered: `judge_prompt_hash ba29d7420a62`, unchanged since
  judgefix; `judge_code_hash 587f0fb8e468`)

One rule this earns beyond the probe rule above: **never patch a judge
mid-freeze** — fix, probe, and only then re-run, because the quoted numbers must
never come from a judge edited after seeing the results.

---

## F07: the submitted deliverable FAILS its own groundedness gate (Aug 2026)

Run (COMPLETION_PLAN Phase 3) against the **checked-in** `deliverables/business_plan.md`
via `run_groundedness_check` directly — **never `compose_capstone.py`, whose `main()`
REGENERATES the plan before gating it**; the plan's sha256 was asserted unchanged.
**89 claims, 0 ERROR (verification complete — a real verdict, not an outage), high-risk
blocking rate 27.4% vs the 5% threshold → GATE FAIL.** The honest reading is two
results: the plan does carry 2 unsourced real-world facts, but 15 of the 17 blockers
are its own projections and operational choices, which no corpus can support — **a 5%
high-risk threshold is structurally unpassable for a projection-genre document**.
Submitted Apr 2026; recorded rather than fixed, which is what the plan's decision point
allows. Full breakdown: `EVAL_NOTES.md` / `HISTORY.md`;
artifacts: `deliverables/{claims,entailment,groundedness_report}`. (Cost: 90 CLI calls
but 79 minutes — `entail_claim` re-retrieves per claim, ~40 min of it cross-encoder.)

---

## `judge_code_hash`: the gate can now see judge LOGIC (Aug 2026)

`judge_prompt_hash` covers rubric TEXT only; two real scoring changes on byte-identical
answers left it unmoved (union → majority voting, 6 blocking errors → 0; and
`_phrase_satisfied` separator folding). `judge_code_hash` (`tracing.code_hash` over
`eval/run._JUDGE_CODE_SYMBOLS`) covers the whole judge decision surface and rides in
the envelope, each record, and the trace. 15 of 25 hard questions route through rule
code — page_lookup is a HYBRID (rule decides 1-vs-3, LLM only 4-vs-5), so both hashes
are load-bearing on six questions at once. `eval/gate.py` WARNS (never fails) on drift
of either hash and **stays stdlib-only — it must never import `eval.run`** (13 s,
pulls torch + chromadb). Before editing `tracing.normalized_source` /
`_code_fingerprint`, read their docstrings and `EVAL_NOTES.md`: four traps each
silently break the naive version (normalized AST, not raw source; sorted sets; regex
`(pattern, flags)`; RAISE on unknown types). New judge helpers MUST be added to
`_JUDGE_CODE_SYMBOLS` — the registry coverage test asserts the known surface.

---

## History

Older changelogs live in `HISTORY.md` — the Weekend-4 design-review fixes (July 2026,
finding IDs F01-F25) and the Weekend 1-3 decisions (BGE-M3, single-collection Chroma,
docling, HyDE, project scoping, idempotent ingest, the eval contract, the groundedness
gate, holdout discipline, verifier temperature). Nothing there is pending; it is kept
because the reason behind each decision still constrains changes.

## How to Run It

Install dependencies:

```
python -m pip install -r requirements.txt
```

First-run model downloads (cached forever):

- BGE-M3 (~2.3GB) on first embed (`~/.cache/huggingface/`).
- BGE reranker v2-m3 (~600MB) on first query (`~/.cache/huggingface/`).
- docling layout + table models (~1GB) on first PDF parse (`~/.cache/huggingface/`).
- easyocr detection + recognition models (~500MB) on first OCR fallback (easyocr cache, only triggers on scanned PDFs).

Ingest a single document:

```
python rag.py ingest path\to\file.pdf
python rag.py ingest path\to\file.docx
```

Bulk ingest a folder:

```
python batch_ingest.py sources\capstone
```

Query commands:

```
python rag.py list
python rag.py list --project capstone
python rag.py projects
python rag.py query "your question"
python rag.py query "your question" --doc <source_name> --project capstone
python rag.py teach "topic" --project capstone
python rag.py analyze "what to analyze" --project capstone
python rag.py summarize --doc <source_name> --project capstone
python rag.py quiz -n 10 --topic "topic" --project capstone
python rag.py chat --project capstone
python rag.py delete <source_name> --project capstone
python rag.py -v query "..."        # DEBUG-level retrieval logging on stderr
```

`<source_name>` is the file stem (filename without extension). Use `python rag.py list` to see exact names. `--project <name>` scopes the command to one project; omit for cross-project semantics on read commands or `default` on write commands.

Run smoke tests:

```
python -m pytest tests/ -m "not slow"   # 74 fast tests, ~2-3 min
python -m pytest tests/ -m slow          # plus the full easy eval, ~20 min
```

Run eval:

```
python eval/run.py                            # easy 20-question regression set
python eval/run.py --hard --holdout tuning    # iterate during development (15 Qs)
python eval/run.py --hard --holdout holdout   # freeze + quote (10 Qs); never tune on these
python eval/run.py --hard                     # everything (25 Qs)
python eval/run.py --hard --judge-runs 5      # tighten judge median (slower)
```

Run regression gate (compares current results to baseline):

```
python eval/gate.py --current eval/results_hard.json --baseline eval/baseline.json
# exits 0 on pass, 1 on fail. Blocks on critical errors NEW since the baseline;
# carried-over ones are printed but do not block.
```

Run the three-arm ablation (see `ABLATION_WRITEUP.md` for the study itself):

```
python tools/build_mirror.py            # arm C corpus mirror, outside the repo
python tools/probe_agentic.py           # 4 pre-flight checks; PLAIN TERMINAL only
python eval/run.py --hard --arm A --judge-runs 3 --judge-evidence corpus --run-id r1
python eval/run.py --hard --arm B --judge-runs 3 --judge-evidence corpus --run-id r1
python eval/run.py --hard --arm C --judge-runs 3 --judge-evidence corpus --run-id r1
python eval/ablation_report.py --suffix _corpus
```

Repeat-sample an arm (second generation seed). The separate `--cache-dir` is
load-bearing: pointed at the default cache the run replays seed 1's answers and
looks healthy while measuring nothing.

```
python eval/run.py --hard --arm A --only h01,h02,h03,h04,h05,h06 --judge-runs 3 \
  --judge-evidence corpus --cache-dir data/answer_cache_seed2 --run-id seed2 --out-suffix seed2
python eval/seed_stability.py --suffix seed2
```

Calibrate the judge:

```
python eval/calibrate.py --runs 5
# writes eval/calibration_results.{json, md}
```

Generate the capstone deliverable (runs the groundedness gate):

```
python compose_capstone.py                # gate blocks if high-risk unsupported > 5%
python compose_capstone.py --force-export # bypass the gate (emergency only)
```

---

## Conventions and Decisions

- **All retrieval goes through `hybrid_search`.** Never call `query_dense`, `query_bm25`, or `generate_hypothetical_answer` from `pipeline.py`. New retrieval behaviour is a parameter on `hybrid_search`, not a bypass.
- **All Claude CLI calls go through `claude_bridge.call_claude`.** `pipeline.py` and `hyde.py` both import it; new callers use the same import.
- **Chunks always carry `source`, `pages`, `project`, `chunker_version`, `embedding_model`, `file_sha256`.** All six are needed for citations + cache key + multi-project isolation. Never drop them.
- **`config.py` is the only place to change models or constants.** No magic numbers in pipeline / retrieval code. Bumping `CHUNKER_VERSION` or changing `EMBEDDING_MODEL` is the right way to invalidate the cache; manual deletion is unnecessary.
- **BM25 invalidation is the caller's responsibility** when chunks change. `pipeline.ingest` and `pipeline.delete_doc` already handle this. Any new code that mutates the collection must call `bm25.invalidate()`.
- **Idempotent ingest by (source, project) pair.** `stable_chunk_id` is `{project}::{source}::{sha1(full text)[:16]}` (`::N` for true duplicates), so the same source in two projects coexists.
- **Output discipline.** Final answers, summaries, quizzes, and the `list` / `projects` outputs go to stdout via `print()` so the user can pipe them. Status updates go through `logger.info` so they can be silenced or routed to the log file.
- **Holdout discipline (D1).** Never tune retrieval, prompts, or judge prompts on holdout results. Iterate using `--holdout tuning`, freeze, then run `--holdout holdout` once before quoting numbers. The MD report header labels which subset was run; trust that label.
- **Verifier calls pass `temperature=0.0` — as INTENT, not as a setting that takes effect.** Judges, entailment, and any verifier-style call pass it so the intent is recorded at the call site. **Neither backend applies it.** The CLI exposes no `--temperature`; and `claude-opus-5` / `claude-sonnet-5` **reject** `temperature` with a 400 — sampling parameters were removed from the Opus 4.7 generation onward. `claude_bridge._call_sdk` therefore accepts and drops it; forwarding it would fail every judge call. Verifier determinism is not purchasable on these models — the measured judge flip-rate is the floor, not a bug to tune away.
- **`citation_page_accuracy_avg` is a FABRICATION check; `citation_claim_support_avg` is an ATTRIBUTION check.** Never present one as the other, and never average across `support_scope`.
- **Critical-error labels are part of the eval contract.** Adding a new label means updating `JUDGE_USER` (eval/run.py), `_VALID_ERRORS` (parser whitelist), and `eval/gate.py::CRITICAL_RULES`. Don't introduce one in just one place.

---

## Known Limitations and Quirks

- **OCR is fallback-only.** easyocr runs per page when PyMuPDF returns less than `OCR_MIN_PAGE_CHARS`; docling's rapidocr handles its own path. Both add latency on image-heavy pages.
- **Tables in non-PDF formats are lossy.** docling keeps PDF tables as markdown, but DOCX flattens to pipe-delimited rows and XLSX renders one sheet as one synthetic page.
- **DOCX page numbers are synthetic.** Citations like "page 4" in a DOCX refer to a 3000-char block, not a real Word page.
- **Token estimation uses `chars // 4`.** Fine for English prose, wrong for code or non-English.
- **`MAX_CONTEXT_CHARS = 150_000`** is a conservative char limit, not model-aware. Both Sonnet and Opus can take more; revisit when model choice changes.
- **Chat history is truncated at 10 turns** in the prompt but the in-memory list grows unbounded. Not a problem at current usage scale.
- **HyDE adds one Sonnet CLI call per qualifying query** (~3-5s), doubling `chat` latency per turn. `should_use_hyde` keeps short / lookup queries on the cheap path; `USE_HYDE = False` disables it.
- **`citation_claim_support_avg` is REPORTED, never gated,** and measures attribution,
  not groundedness. Its blind spots — citation-carrying spans only; union evidence, so
  page-level precision is still unmeasured (h06's ceiling invisible); synthesis scored
  unfairly; token-recall quote check passes reordered source words; same-family
  uncalibrated LLM stage; value depends on `--support-runs` and `support_scope`, never
  quote across either — are catalogued in full in `EVAL_NOTES.md`.
- **First docling call downloads ~1 GB of models;** first easyocr call downloads ~500 MB. Both cache forever after that.

---

## SDK backend (Aug 2026, COMPLETION_PLAN Phase 5)

`claude_bridge` now has two backends behind `config.BRIDGE_BACKEND`. **Default is
`cli`** — plan limits stay the shipped contract. `sdk` gets a real system role
(the CLI concatenates system+user on stdin), typed exceptions instead of stdout
sniffing, and `max_retries=3`.

- **Double opt-in, and the reason is an inversion.** `_plan_auth_env()` *strips*
  `ANTHROPIC_API_KEY` because the CLI puts it ahead of subscription OAuth and
  would meter every call. The SDK *requires* that key. Same variable, opposite
  handling — so the guard is per-backend and SDK mode needs BOTH
  `PDFRAG_BRIDGE=sdk` and `PDFRAG_ALLOW_API_KEY=1`. One env var must never be
  able to start a bill.
- **`temperature` is accepted and DROPPED on the SDK path.** Sampling parameters
  were removed from the Opus 4.7 generation onward: `claude-opus-5` and
  `claude-sonnet-5` return **400** if a request carries `temperature`. Every
  verifier call in this project passes `temperature=0.0`, so forwarding it would
  fail every judge and entailment call. The plan justified this phase partly on
  "an honoured `temperature=0`" — that payoff does not exist.
- **Model IDs map through `config.MODEL_IDS`** (`sonnet`→`claude-sonnet-5`,
  `opus`→`claude-opus-5`, `haiku`→`claude-haiku-4-5`). CLI aliases 404 as API
  model IDs, so `compose_capstone.py` / `groundedness.py` no longer hardcode
  them; a test greps all four call-site modules to keep it that way.
- **`call_claude_json`'s envelope is synthesized** on the SDK path so
  `total_input_tokens` and `eval/ablation_report.py` work unchanged — a test
  asserts it still recovers 44,086 from the `input_tokens=1` cache-served shape.
- `RateLimitError` / `AuthenticationError` → `SessionLimitError`, so runs still
  checkpoint and stop rather than scoring an outage as a wrong answer.

Verified with one live SDK call (Aug 2026) and 6 mocked tests. `anthropic` is an
optional dependency — the default backend never imports it.

---

## Rerank: measured, and kept ON (Aug 2026, COMPLETION_PLAN Phase 4)

`--no-rerank` exists on `rag.py query` and `eval/run.py`. Measured cost: rerank is
~26.6s of every query (retrieval-only mean 30.6s vs 4.0s) — also ~40 of the 79 minutes
the deliverable groundedness gate spends, since `entail_claim` re-retrieves per claim.
The paired quality run (tables in `EVAL_NOTES.md`, full working in `HISTORY.md`) says
keep it ON: 12 of 15 questions score identically and the entire difference is **h04**,
where chunk `[2,3,4]` is the ONLY chunk containing both `7,200` and `522` — rerank
ranks it 6th, inside the window; no-rerank drops it from the top-10 and the answer
breaks with a `WRONG_EVIDENCE`. One instance of exactly what a cross-encoder is for.
Revisit only if latency ever matters more than a WRONG_EVIDENCE.

**The retrieval metrics moved the WRONG WAY, and that is the durable finding.** MRR@10
and nDCG@10 both *improved* on the run that produced the critical error (page-OVERLAP
matching against chunk-shaped gold rewards a boundary-sharing chunk holding neither
number), and both sit in `eval/gate.py::DEFAULT_TOLERANCES` — the gate can pass, even
reward, a retrieval change that degrades answers. Do not read them as answer-quality
proxies.

---

## Roadmap

1. Extend the SDK backend beyond parity: streaming, prompt caching, and
   `output_config.effort`. The switch itself is done (see the SDK section above);
   what is missing is the features the SDK makes newly *possible*.
2. Promote `citation_claim_support_avg` into `eval/gate.py::DEFAULT_TOLERANCES` — but
   only after (a) two seeds at `--support-runs 3` show run-level drift below half the
   proposed tolerance and (b) its `flip_rate` is under 0.10. Set the tolerance to
   `max(0.10, 3x measured drift)` and land the promotion as its own one-line commit.
   Until then it is reported and inert by design.
3. **Split the deliverable groundedness gate by claim genre** — F07 is now run (see
   above) and the plan FAILS at 27.4%, but 15 of its 17 blocking claims are the plan's
   own projections and operational choices, which no corpus can support. Until
   "asserts an external fact" is separated from "projects its own future", the
   threshold is not measuring what it should.
4. **Stop treating `mrr_at_10` / `ndcg_at_10` as answer-quality proxies in the gate.**
   Phase 4 produced a case where both improved on the run that generated a critical
   error, because page-OVERLAP matching against chunk-shaped gold rewards a chunk that
   shares a boundary page but holds none of the facts. Either match on fact presence or
   demote both to reported-only.
5. Optionally extend the second seed to the other 19 questions. They were
   all-arms-identical in the single run there is, and the two reseeded controls
   showed zero drift, so new discordance is unlikely — but it is the only
   untested direction left in the ablation.
6. Optional: FastAPI/Gradio UI; per-language OCR; conversation persistence in `chat`.

