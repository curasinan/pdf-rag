# PDF RAG Study Tool

A local RAG pipeline for studying from PDFs that exceed Codex's context window. Ingest PDFs (and DOCX) into a vector store, then query, summarize, teach, quiz, or chat against the material via the Codex CLI.

This file is the project memory for Codex. Read it before making non-trivial changes.

---

## Architecture

Single-collection ChromaDB (1024-dim BGE-M3 vectors) plus an in-memory BM25 keyword index, fused via Reciprocal Rank Fusion, then reranked with a cross-encoder. Generation goes through the Codex CLI (uses plan limits, not the paid API).

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
| `claude_bridge.py` | Single point for every Codex call. Two backends behind `config.BRIDGE_BACKEND`: **`cli`** (default — `Codex -p`, plan limits, no API charges) and **`sdk`** (Anthropic SDK, METERED billing, double-opt-in). `call_claude_agentic` is CLI-only unconditionally. |
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
| `eval/baseline.json` | Snapshot the gate compares against. Regenerated Aug 2026 under the corrected judge rubric (`--arm A --judge-runs 3 --judge-evidence own`, run `judgefix`); pre-rubric copy in `.backup_judgefix/`, pre-Weekend-3 one in `eval/baseline_legacy.json`. |
| `eval/calibration.json` | 25 calibration anchors with bootstrapped human labels (`bootstrap_method="prior_verdict_mapping"`). |
| `eval/calibrate.py` | Runs the judge N times per anchor; reports per-axis accuracy / flip-rate / confusion. |
| `eval/bootstrap_calibration.py` | One-shot: rebuilds `calibration.json` from a prior eval results file. |
| `eval/oracle.py` | Oracle-context harness. Re-runs failures with gold-only chunks; classifies retrieval vs generation failure. |
| `eval/arms.py` | Answer producers — the one seam where arms differ. `Production` + `ArmAHybridRAG` / `ArmBFullContext` / `ArmCAgenticFiles` + `make_producer`. Downstream of `produce()` is arm-agnostic. |
| `tools/build_mirror.py` | Builds arm C's plain-text corpus mirror from `pdf_parser.extract_pages` (the extraction arm A ingests). Asserts every stored chunk's text is present; refuses OS-redirected paths. |
| `tools/probe_agentic.py` | Arm C pre-flight: envelope shape, sandbox leak, memory leak, citation parseability. **Plain terminal only.** |
| `tools/diagnose_agentic_auth.py` | Bisects CLI auth failures (API key vs flags vs no login). Found the `ANTHROPIC_API_KEY` billing trap. |
| `tools/probe_citation_support.py` | Plants a clean / miscited / fabricated-page citation and asserts the last two are caught. Run after ANY support-prompt edit, and bump `CITATION_SUPPORT_PROMPT_VERSION`. |
| `tools/probe_judge.py` | Plants a clean / fabricated / miscited answer at the judge and asserts it still catches the last two. Run after ANY rubric edit. |
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
| `ABLATION_NOTES.md` | Build traps from the finished ablation, moved out of this file to keep it light. Read before re-running or extending the study. |
| `ABLATION_WRITEUP.md` | The ablation study's written report: method, paired statistics, threats, conclusion. The shareable deliverable; `eval/ablation_report_corpus.md` holds the generated tables. |
| `compose_capstone.py` | One-shot deliverable generator. Runs G2 groundedness gate between plan generation and DOCX/PDF/PPTX/XLSX export. `--force-export` bypasses the gate. |
| `tests/test_smoke.py` | pytest smoke suite (56 fast tests). `pytest -m "not slow"` for fast runs; `pytest -m slow` runs the full hard eval + regression gate. |

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
  subprocess; escape hatch `PDFRAG_ALLOW_API_KEY=1`. A `Codex` subprocess spawned
  inside a Codex session also cannot authenticate until the CLI has been logged
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
24/25, every generation replayed from cache. The arms are separated by less than
the judge's own noise. Critical-error counts are **unioned across judge runs** in
this pass, so they grow with the run count and are comparable only between arms
within one pass.

### Both of arm A's losses are architectural, not tuning

- **h01** — retrieval never surfaced the answer. Gold is page 8; the top-10 held
  chunks `[1,2,3]` and `[4,5,6]` of the right document plus unrelated sources.
  `MRR=0.0`. Arms B and C both answered it. This was the design review's
  motivating example and it survives every Weekend-4 retrieval fix.
- **h06** — retrieval *succeeded* (`MRR=1.0`) but the answer could only cite
  `pages 1-3`, the merged chunk, instead of page 2. Chunking destroys page-level
  citation precision. **Mechanism confirmed by the second seed, verdict not:** arm
  B's reseeded answer states the same ceiling in the same terms yet scored
  EQUIVALENT/4 where the first scored DIFFERENT/2. Cite h06 as a mechanism, never
  as a tally.

### Threats to validity

n=25 with a 30pp MDE; one generation run per arm on 19 of 25 questions (the 6
`page_lookup` ones, which carry all the paired signal, were reseeded — next
section); **arm B only exists because the 286K-char corpus fits in context**, so
above ~200K tokens that arm disappears and the comparison is vacuous; arm C's
system prompt necessarily includes Codex's agent scaffolding; arm B's prompt
carries a completeness preamble; arm C gets an `_INDEX.md` affordance; judges are
same-family as the generator.

---

## SECOND GENERATION SEED (Aug 2026) — what replicated and what didn't

Report: `eval/seed_stability_seed2.md`. Each arm had run once per question, so
every quality number was one draw. Fixing that was cheap because **21 of 25
questions scored 5/5/5 across all arms** and contribute zero to every paired
delta: the published A-vs-C delta of -0.28 is exactly (3-5)+(4-5)+(4-5)+(2-5)
over h01/h02/h05/h06, ÷ 25. Four questions carry the whole quality conclusion.

Two traps, both load-bearing:

- **Reseed the stratum, not the discordant set.** Those four were *selected* for
  being extreme, so regression to the mean shrinks the gap whether or not the
  effect is real. The run covers all six `page_lookup` questions — h03/h04 are
  same-type controls, and without them the drift numbers are uninterpretable.
- **Use a separate `--cache-dir`, never `--no-cache`.** The answer cache is
  content-addressed, so a reseed on the default cache replays seed 1 and looks
  healthy while measuring nothing. A separate dir also keeps seed 2 cached, so
  re-judging is free. `--out-suffix` (new) stops it overwriting seed 1 and the
  July pilot files.

| view | A | B | C | A vs C Δrel [95% CI] | B vs C discordant |
|---|---|---|---|---|---|
| seed 1 | 23/25 | 24/25 | 25/25 | -0.28 [-0.60, -0.04] | 1 |
| seed 2 | 23/25 | **25/25** | 25/25 | -0.28 [-0.68, +0.00] | **0** |
| pooled | 23/25 | 24/25 | 25/25 | -0.28 [-0.60, -0.02] | 1 |

- **A vs C reproduced exactly** (-0.28 three times; pooled CI still excludes zero).
  **B vs C collapsed** — zero discordant pairs in seed 2.
- **Drift sits where the signal is:** 0 flips in 6 control cells vs 25% of
  discordant cells. Per-arm verdict flips A 2/6, B 1/6, C 0/6 — six cells give
  useless intervals (C's 0/6 still admits 0.46), so the ordering is suggestive only.
- **Arm A's retrieval is deterministic** — byte-identical chunk sets and unchanged
  MRR@10 on all six. Its drift is entirely downstream of retrieval, and h01's miss
  (MRR 0.0 twice) is a reproducible pipeline property, not a bad draw.
- **h01's 3 → 1 drop is a substring artifact.** Both answers correctly report the
  context lacks KPI #5; seed 1's happened to contain the literal `table turn` and
  seed 2's did not, so `_judge_page_lookup`'s `must_contain` branch scored them 3
  and 1. When an arm is failing anyway, that judge grades incidental phrasing.

---

## Recent Changes (post-ablation, Aug 2026 — baseline + judge aggregation)

- **`eval/baseline.json` regenerated** from `--arm A --judge-runs 3 --judge-evidence
  own`, which also produced `eval/results_hard.json` — the path the gate defaults to,
  which had never existed. The legacy file lacked `mrr_at_10`, `ndcg_at_10`, `judge`,
  `citation_validation` and `holdout`, so the gate was silently SKIPping five of six
  tracked metrics. Old file kept as `eval/baseline_legacy.json`. (Re-regenerated after
  the rubric fix below.)
- **Critical errors are MAJORITY-voted across judge runs, not unioned**
  (`_judge_llm_aggregated`). Scores already used the median, so one dissenting run
  could not move them — but it *could* brand an answer with a gate-blocking error, and
  the false-positive count grew with `--judge-runs` by construction (10 violations, 4
  flagged by exactly 1 of 3, on answers judged EQUIVALENT at relevance 4-5). Published
  ablation error counts predate this.
- **The regression gate blocks on NEW critical errors, not all of them**
  (`eval/gate.py`). Absolute blocking is right for the deliverable groundedness gate
  but wrong for a *regression* gate, where it conflates "this system has known issues"
  with "this change made it worse" — it was permanently red and useless. Carried-over
  errors print without blocking; a new question or label blocks; no baseline restores
  absolute behaviour.
## The six "carried-over defects" were the rubric, not the system (Aug 2026)

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
  `_quote_is_in_candidate` drops votes whose quote is absent from the answer. The only
  mechanical guarantee here. Fails **open** on an empty quote so pre-change `per_run`
  rows re-aggregate byte-identically — never tighten that to fail-closed.

Full re-judge (same cached answers, `--judge-runs 3 --judge-evidence own`): **6 → 0
blocking errors, none new**, every clearance *unanimous* (3/3 NONE), so the rubric did
the work, not the vote filter. Axis means +0.24 rel / +0.44 gnd / +0.68 cit; verdicts
unchanged 24/25; retrieval byte-identical. h05/h06 are **holdout**, were excluded from
the fix design, and cleared without ever being looked at.

**Run `python tools/probe_judge.py` after any rubric edit.** A change that clears errors
looks identical to one that blinded the judge until you plant defects: it feeds a clean,
a fabricated-statistic and a miscited answer and asserts the last two are still caught.

Also: rationales no longer truncate at 300 chars (`_MAX_RATIONALE_CHARS`) — h07's was
cut mid-word at "and several oth", destroying the record of *why* it flagged; and the
envelope now carries `judge_prompt_hash` / `qa_prompt_hash`, with `eval/gate.py` warning
(never failing) when the rubric differs from the baseline's or the baseline predates it.

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
python -m pytest tests/ -m "not slow"   # 56 fast tests, ~2-3 min
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
- **All Codex CLI calls go through `claude_bridge.call_claude`.** `pipeline.py` and `hyde.py` both import it; new callers use the same import.
- **Chunks always carry `source`, `pages`, `project`, `chunker_version`, `embedding_model`, `file_sha256`.** All six are needed for citations + cache key + multi-project isolation. Never drop them.
- **`config.py` is the only place to change models or constants.** No magic numbers in pipeline / retrieval code. Bumping `CHUNKER_VERSION` or changing `EMBEDDING_MODEL` is the right way to invalidate the cache; manual deletion is unnecessary.
- **BM25 invalidation is the caller's responsibility** when chunks change. `pipeline.ingest` and `pipeline.delete_doc` already handle this. Any new code that mutates the collection must call `bm25.invalidate()`.
- **Idempotent ingest by (source, project) pair.** `stable_chunk_id` is `{project}::{source}::{sha1(full text)[:16]}` (`::N` for true duplicates), so the same source in two projects coexists.
- **Output discipline.** Final answers, summaries, quizzes, and the `list` / `projects` outputs go to stdout via `print()` so the user can pipe them. Status updates go through `logger.info` so they can be silenced or routed to the log file.
- **Holdout discipline (D1).** Never tune retrieval, prompts, or judge prompts on holdout results. Iterate using `--holdout tuning`, freeze, then run `--holdout holdout` once before quoting numbers. The MD report header labels which subset was run; trust that label.
- **Verifier calls pass `temperature=0.0` — as INTENT, not as a setting that takes effect.** Judges, entailment, and any verifier-style call pass it so the intent is recorded at the call site. **Neither backend applies it.** The CLI exposes no `--temperature`; and `Codex-opus-5` / `Codex-sonnet-5` **reject** `temperature` with a 400 — sampling parameters were removed from the Opus 4.7 generation onward. `claude_bridge._call_sdk` therefore accepts and drops it; forwarding it would fail every judge call. Verifier determinism is not purchasable on these models — the measured judge flip-rate is the floor, not a bug to tune away.
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
- **`citation_claim_support_avg` is REPORTED, never gated,** and measures a different
  thing from `citation_page_accuracy_avg`. What it cannot see, bluntly:
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
  were removed from the Opus 4.7 generation onward: `Codex-opus-5` and
  `Codex-sonnet-5` return **400** if a request carries `temperature`. Every
  verifier call in this project passes `temperature=0.0`, so forwarding it would
  fail every judge and entailment call. The plan justified this phase partly on
  "an honoured `temperature=0`" — that payoff does not exist.
- **Model IDs map through `config.MODEL_IDS`** (`sonnet`→`Codex-sonnet-5`,
  `opus`→`Codex-opus-5`, `haiku`→`Codex-haiku-4-5`). CLI aliases 404 as API
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

## Rerank: the knob is now measurable (Aug 2026, COMPLETION_PLAN Phase 4)

`hybrid_search` always had `use_rerank`, but no caller could reach it, so the
cross-encoder's cost had never been measured against its benefit. `--no-rerank` now
exists on `rag.py query` and `eval/run.py`.

Local retrieval-only timing, 3 queries, this machine:

| | q1 | q2 | q3 | mean |
|---|---|---|---|---|
| rerank ON | 29.0s | 39.0s | 23.8s | **30.6s** |
| rerank OFF | 0.1s | 11.6s | 0.1s | **4.0s** |

(q2's 11.6s with rerank off is the HyDE call, not the reranker.) Rerank is ~26.6s of
every query — consistent with the ablation's finding that retrieval is 70% of arm A's
wall clock. **The quality half of the decision is not made:** it needs a paired
`--no-rerank` eval against a rerank run, which is a plan-quota run and belongs to you.

Two things make that A/B safe: `use_rerank` is inside `ArmAHybridRAG.config_hash()`, so
the content-addressed answer cache cannot replay reranked answers into a no-rerank run
(the failure that made a separate `--cache-dir` load-bearing for seed 2); and the MD
report carries a loud `RERANK DISABLED` banner so such a run can never be read as a
default one.

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
3. Run the deliverable groundedness gate against the checked-in `deliverables/`
   (review finding F07: `claims.json` / `entailment.json` / `groundedness_report.md`
   are still absent, so the submitted plan was never verified by it).
4. Optionally extend the second seed to the other 19 questions. They were
   all-arms-identical in the single run there is, and the two reseeded controls
   showed zero drift, so new discordance is unlikely — but it is the only
   untested direction left in the ablation.
5. Optional: FastAPI/Gradio UI; per-language OCR; conversation persistence in `chat`.

---

## Migration Note

If you pulled these weekend-1 changes and the old `data/chromadb/` folder still exists, it's safe to delete. The new pipeline reads/writes from `data/chroma_v2/` and ignores the old path. If you re-ingest, BGE-M3 will populate `data/chroma_v2/` and the old folder becomes dead weight.

```
Remove-Item -Recurse -Force data\chromadb
```
