# Weekend-2 Completion Plan (Revised)

## Status going in

- Hybrid retrieval (BGE-M3 + BM25 + RRF + cross-encoder rerank + per-source quota) is running.
- 23 sources ingested, ~53 chunks. Eval shows 20/20 EQUIVALENT, 100% recall@10. The current eval is a regression alarm; it has no measurement headroom for further quality changes.
- Three baselines saved: `eval/results_baseline.*` (v1), `eval/results_v2_bootstrapped.*` (v2), `eval/results_v3_quota.*` (v3 = current behavior).

## Phase ordering rationale

1. Architectural changes first (Phase 0) so the only re-ingest happens at Phase 5 with the right shape.
2. Measurement layer second (Phase 1) so every later change is quantifiable.
3. Foundational quality-of-life next (Phase 2 logging, Phase 3 caching) before invasive changes.
4. Quality changes in dependency order: HyDE (no re-ingest), docling (re-ingest required), OCR (additive backend).
5. Ablation eval at Phase 5b to isolate HyDE × docling interaction.
6. Smoke tests last so they cover the final shape of the codebase.

---

## Phase 0 — Multi-project isolation (30-45 min)

**Why first.** "Growing personal projects" requires this architectural decision. Doing it after Phase 5's re-ingest doubles the work. Doing it now means every later phase is correctly scoped from day one.

**Design.** Add a `project` metadata field to every chunk. Default project is `"default"`. CLI gains a `--project` flag on every command. `hybrid_search` accepts a `project` filter. Single ChromaDB collection stays.

**Files to modify**

- `config.py` — add `DEFAULT_PROJECT = "default"`.
- `vectorstore.py`:
  - `add_chunks` / `replace_document` — accept `project` arg, store in metadata.
  - `query_dense`, `get_all_chunks`, `list_documents`, `count_chunks`, `delete_document` — accept and apply `project` filter via Chroma `where`. When both `source` and `project` filters apply, combine via `$and`.
  - New `list_projects() -> list[str]`.
- `bm25.py` — `query_bm25` accepts `project`, filters chunks before scoring.
- `retrieval.py` — `hybrid_search` accepts `project`, threads through to dense and sparse channels.
- `pipeline.py` — `ingest(path, project)` and every other command accept and apply project.
- `rag.py` — add `--project` (default `default`) to every subparser; new `projects` subcommand listing projects with chunk counts.
- `batch_ingest.py` — accept `--project`.

**One-shot migration.** Run a small Python snippet that calls `coll.update(ids=..., metadatas=...)` to set `project="capstone"` on all existing chunks before continuing. Alternative: temporarily set `DEFAULT_PROJECT="capstone"`, leave existing data alone, change back later.

**Verification**

- `python rag.py projects` shows the migrated project with its chunk count.
- `python rag.py query "test" --project capstone` works.
- Old commands without `--project` still work (default applies).

---

## Phase 1 — Hard eval expansion (1.5-2 h)

**Why before Phase 2+.** Current eval is at 20/20. Without harder questions, every later change is invisible.

### Schema redesign

`eval/questions.json` keeps the existing 20 questions as the regression alarm. New `eval/questions_hard.json` uses an extended schema:

```json
{
  "id": "h01",
  "question": "Compare break-even formulas across the coffee-shop docs",
  "question_type": "synthesis",
  "must_cite_sources": [
    {"source": "Calculating Your Break Even Point", "pages": [2, 3]},
    {"source": "Briefing Doc - Opening and Operating a Profitable Coffee Shop", "pages": [4]}
  ],
  "expected_answer": "...",
  "must_contain": ["fixed costs", "gross margin"]
}
```

Notes on the schema:

- `question_type` ∈ `{"qa", "synthesis", "numeric", "negative", "page_lookup"}`.
- `must_cite_sources` is always a list, even for single-source questions.
- `must_contain` is optional, used by judge logic for `numeric` and `page_lookup` types.

### Recall metrics

For each ground-truth source `s_i`:

- `recall_source(s_i)` = `s_i.source` appears in retrieved top-K.
- `recall_pages(s_i)` = at least one retrieved chunk has `source==s_i.source` AND any page ∈ `s_i.pages`.

Aggregate per question:

- `recall_full` = every `s_i` has `recall_source` (all required sources represented).
- `recall_partial` = mean of `recall_source` over `s_i` (0..1).
- `recall_pages_full` = every `s_i` has `recall_pages`.

Headline metrics for each run: `recall_full %` and `recall_pages_full %`. Partial recall reported as secondary.

### Judge logic by type

- `qa` and `synthesis`: existing judge prompt (EQUIVALENT / PARTIAL / DIFFERENT).
- `numeric`: regex-extract numbers from expected and actual; compare with ±5% tolerance per number. EQUIVALENT iff all expected numbers found within tolerance, PARTIAL if at least one match, DIFFERENT if none.
- `negative`: actual answer passes if it contains any of `["no", "not mentioned", "doesn't mention", "no mention", "not in the materials", "i don't see"]` (case-insensitive). Otherwise fall through to standard judge.
- `page_lookup`: substring check against `must_contain`; EQUIVALENT if all required strings present, otherwise PARTIAL/DIFFERENT depending on coverage.

### Question coverage (target: 25 questions)

- 6 page-lookup ("what is on page 5 of Briefing Doc?", "what page defines table turn time?")
- 5 cross-doc synthesis (compare/contrast between 2-3 docs)
- 5 numeric extraction (financial model values, KPI thresholds, cost percentages)
- 5 specific detail recall (deep questions about specific sections)
- 4 negative cases (topics genuinely not in any doc, e.g. "does any doc mention quantum computing?")

### Files to modify

- `eval/questions_hard.json` — new file with 25 questions.
- `eval/run.py`:
  - `--hard` flag loads `questions_hard.json`.
  - New per-type judge functions: `_judge_numeric`, `_judge_negative`, `_judge_page_lookup`. Existing judge stays as `_judge_qa`.
  - New recall computation handling `must_cite_sources` list.
  - Output schema includes per-source recall breakdown so failures can be debugged.

### Verification

- `python eval/run.py` (easy) → still 20/20.
- `python eval/run.py --hard` → produces baseline numbers. Save as `eval/results_v4_hard_baseline.{json,md}`. Expect lower recall and correctness; that's the measurement headroom.

---

## Phase 2 — Logging + verbose (1 h)

**Why now.** Every later phase will benefit from real debug output. Replacing `print()` calls is cheap.

### Files to add/modify

- New `logging_setup.py`:

```python
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from config import DATA_DIR

def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    fmt = "%(asctime)s %(levelname)-7s %(name)-15s %(message)s"
    log_dir = Path(DATA_DIR) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handlers = [
        logging.StreamHandler(),
        RotatingFileHandler(
            log_dir / "rag.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8",
        ),
    ]
    logging.basicConfig(level=level, format=fmt, handlers=handlers, force=True)
```

- `rag.py` — top-level `--verbose` / `-v` flag, calls `setup_logging` before dispatch.
- `pipeline.py` — replace every `print()` with `logger.info()` / `logger.error()`. Keep the final answer body printing as `print()`; the user wants the answer on stdout, not the log.
- `retrieval.py` — `logger.debug()` for per-stage candidate counts: dense, sparse, fused, reranked, post-quota. This is the single most useful debug surface for retrieval.
- `bm25.py` — log cache hit/miss/rebuild at debug level.
- All other modules: `logger = logging.getLogger(__name__)` at module top.

### Verification

- `python rag.py list` → no log noise on stdout, file gets one INFO line.
- `python rag.py -v query "test"` → debug lines visible: candidate counts, rerank pool, quota application, Claude CLI timing.
- `data/logs/rag.log` accumulates and rotates at 5MB.

---

## Phase 3 — Content-hash idempotency (45 min)

**Why now.** Before Phase 5's re-ingest. With the cache key in place, switching back and forth between docling and PyMuPDF for ablation comparisons becomes single-command instead of full re-ingest.

### Cache key composition

The cache is valid iff all three match:

```python
cache_valid = (
    stored_file_sha256 == new_file_sha256
    and stored_chunker_version == CHUNKER_VERSION
    and stored_embedding_model == EMBEDDING_MODEL
)
```

When any component changes, re-ingest. This handles file changes (Phase 3), chunker swaps (Phase 5), and any future embedding model swap without manual intervention.

### Files to modify

- `pdf_parser.py` — `file_sha256(path: str) -> str` helper (read in 1 MB chunks via `hashlib.sha256`).
- `config.py` — `CHUNKER_VERSION = 1` (will be bumped to `2` in Phase 5).
- `vectorstore.py`:
  - `add_chunks` stores `file_sha256`, `chunker_version`, `embedding_model` in metadata for every chunk.
  - New `get_source_metadata(source) -> dict | None` returns the cache-key triple from any one of the chunks for that source.
- `pipeline.py`:
  - `ingest()` — compute `new_hash = file_sha256(path)`. If `get_source_metadata(source_stem)` exists and all three values match current config, log `"unchanged, skipping"` and return a `Status.CACHED` enum. Otherwise proceed with `replace_document`.
- `batch_ingest.py` — print `[N/M] file (cached)` when ingest returns `Status.CACHED`.

### Verification

- `python batch_ingest.py sources/capstone` → first run normal.
- `python batch_ingest.py sources/capstone` → second run reports all 24 cached, finishes in <5 s.
- Touch one file (e.g. open + save in Word) → only that one re-ingests on next batch run.

---

## Phase 4 — HyDE query rewriting (2-3 h)

**Why before docling.** No re-ingest needed, easy to ablate via `USE_HYDE` toggle, gives a measurable quality data point on the current chunker before changing chunker.

### Architecture

Three-way RRF: original-query dense, hypothetical-answer dense, original-query BM25.

```python
def hybrid_search(query, ..., use_hyde=USE_HYDE):
    if use_hyde and should_use_hyde(query):
        hyde_text = generate_hypothetical_answer(query)
        q_vec = embed_texts([query])[0]
        h_vec = embed_texts([hyde_text])[0]
        dense_q = query_dense(q_vec, n_results=RETRIEVAL_CANDIDATES, source=source, project=project)
        dense_h = query_dense(h_vec, n_results=RETRIEVAL_CANDIDATES, source=source, project=project)
        sparse  = query_bm25(query, n_results=RETRIEVAL_CANDIDATES, source=source, project=project)
        fused = reciprocal_rank_fusion([dense_q, dense_h, sparse])
    else:
        # existing 2-way path
```

### When to skip HyDE

```python
def should_use_hyde(query: str) -> bool:
    words = query.split()
    if len(words) < HYDE_MIN_QUERY_WORDS:        # 5
        return False
    if '"' in query:                              # exact-match queries
        return False
    if query.lower().startswith(("find ", "locate ", "where is ", "what page")):
        return False
    return True
```

This filter prevents HyDE from hallucinating answers for short / lookup queries, which would degrade recall on those cases.

### Files to add/modify

- New `claude_bridge.py` — moves `_call_claude` out of `pipeline.py` so both `pipeline.py` and `hyde.py` can import it without a circular reference.
- New `hyde.py`:
  - `generate_hypothetical_answer(query: str) -> str` — calls `_call_claude(MODEL_FAST, HYDE_SYSTEM, HYDE_USER.format(query=query))`.
  - `should_use_hyde(query: str) -> bool` — heuristic above.
- `prompts.py` — add `HYDE_SYSTEM` ("Write a short, factually plausible passage that would answer the question below as if it were excerpted from a document. 2-4 sentences.") and `HYDE_USER`.
- `retrieval.py` — accept `use_hyde`, branch on `should_use_hyde`.
- `config.py`:
  - `USE_HYDE = True`
  - `HYDE_MIN_QUERY_WORDS = 5`
- `pipeline.py` — import `_call_claude` from `claude_bridge`.

### Cost note

Each HyDE-eligible query gains one Sonnet CLI call (~3-5 s, one plan-limit slot). For interactive `chat` mode, this doubles latency per turn. For batch operations (eval, summarize), proportionally more expensive. Document this in CLAUDE.md.

### Verification

- `python eval/run.py` → still 20/20 (no regression on easy).
- `python eval/run.py --hard` → save as `eval/results_v5_hyde.{json,md}`. Compare to v4 baseline. Expect synthesis questions to improve, page-lookup unchanged (filtered by `should_use_hyde`).

---

## Phase 5 — Chunker swap to docling (3-5 h)

**Why now.** Biggest expected quality lever for tables, headings, and structured content.

### Pre-flight install test (mandatory)

Before writing any code:

```
python -m pip install docling
python -c "from docling.document_converter import DocumentConverter; print('ok')"
```

If install fails on Python 3.14 (likely; docling has heavy ML deps that may not have 3.14 wheels yet), pick a fallback before continuing:

- **Fallback A (recommended).** Create a Python 3.12 venv just for this project, reinstall everything in it. Document the venv path in CLAUDE.md.
- **Fallback B (lighter).** Use `pymupdf4llm` (PyMuPDF's markdown export) instead of docling. Worse table extraction but works on 3.14 with no extra ML deps.

If install succeeds, proceed with docling.

### Design

Add `_extract_with_docling(path)` backend producing the existing `{page_num, text}` pages contract, with one improvement: `text` now contains markdown-formatted tables, preserved heading levels (`# H1`, `## H2`), and preserved list structure. The chunker handles this transparently because markdown is just text.

For PDF, use docling's PDF converter. For DOCX and XLSX, **keep current backends** (python-docx, openpyxl). Docling's primary win is PDF table extraction; switching DOCX/XLSX adds install cost for marginal benefit.

Section-aware chunking. When pages contain `# ` or `## ` headers, prefer splitting on those boundaries first, falling back to paragraph boundaries (current logic) only when a section exceeds `CHUNK_SIZE_CHARS`. Implementation:

```python
def chunk_pages(pages, source, chunk_size, overlap):
    # Split each page into "units" with priority:
    #   1. Lines starting with "# " or "## " mark hard boundaries
    #   2. "\n\n" paragraph splits as soft boundaries
    # Greedily accumulate, preferring to break at hard boundaries.
    ...
```

### Files to modify

- `pdf_parser.py`:
  - New `_extract_with_docling(pdf_path)` (PDF only; DOCX and XLSX stay on existing backends).
  - `extract_pages` dispatches: PDF → docling if `USE_DOCLING` and import succeeded, else PyMuPDF.
  - `chunk_pages` updated for section-aware splitting.
- `config.py`:
  - `USE_DOCLING = True`
  - `CHUNKER_VERSION = 2` (bumped, invalidates Phase 3 cache automatically).
- `requirements.txt` — add `docling>=2.0` (or fallback dep if Plan B chosen).

### Re-ingest

`CHUNKER_VERSION` bump invalidates all cached files via Phase 3's cache key. Run:

```
python batch_ingest.py sources/capstone --project capstone
```

Expected ingest time: 3-5x slower than current (docling table extraction is computationally heavy). For the 23-file capstone corpus this means roughly 20-40 minutes vs. the current 5-10. Warn the user before kicking off.

### Verification

- `python eval/run.py` (easy) → must stay 20/20.
- `python eval/run.py --hard` with `USE_HYDE=False` → save as `eval/results_v6_docling.{json,md}`.
- Numeric and table questions (financial-model 2030 cash, KPI thresholds, COGS percentages) should improve materially. Cross-doc synthesis should also improve modestly because section headings now persist into chunk text.

---

## Phase 5b — Ablation eval (15 min)

**Why.** Without this you can't tell whether HyDE or docling drove the improvement, and they may interact poorly.

### Procedure

Run hard eval in four configurations and save results separately:

| Config | USE_HYDE | Chunker | Save as |
|---|---|---|---|
| v4_hard_baseline | False | PyMuPDF | (already saved) |
| v5_hyde | True | PyMuPDF | (already saved) |
| v6_docling | False | docling | (already saved) |
| v7_hyde_docling | True | docling | new |

For v7: set `USE_HYDE=True` in config, run `python eval/run.py --hard`, save as `eval/results_v7_hyde_docling.{json,md}`.

### Decision rule

Compare:
- v4 vs v6: chunker effect alone
- v4 vs v5: HyDE effect alone
- v4 vs v7: combined effect

If `v7 < max(v5, v6)`, the two interventions interact poorly — disable the lower-impact one. If `v7 ≥ max(v5, v6)`, keep both. Record the decision in CLAUDE.md.

---

## Phase 6 — OCR fallback (1-2 h)

**Why now.** Defensive infrastructure for future scanned PDFs. The current corpus doesn't trigger this path.

### Design

Per-page fallback (not whole-doc):

```python
def _extract_pdf_pages(pdf_path):
    doc = fitz.open(pdf_path)
    pages = []
    needs_ocr = []
    for i, page in enumerate(doc):
        text = page.get_text()
        if len(text.strip()) < OCR_MIN_PAGE_CHARS:   # 50
            needs_ocr.append((i, page))
        elif text.strip():
            pages.append({"page_num": i + 1, "text": text})
    if needs_ocr and USE_OCR_FALLBACK:
        ocr_pages = _ocr_pages(needs_ocr)
        pages.extend(ocr_pages)
    pages.sort(key=lambda p: p["page_num"])
    doc.close()
    return pages
```

OCR backend: `easyocr`. Pure Python, no Tesseract install needed on Windows. First use downloads ~500 MB of detection + recognition models into the easyocr cache.

### Files to modify

- `pdf_parser.py` — `_ocr_pages(pages)` helper using easyocr; per-page fallback in `_extract_pdf_pages`.
- `config.py`:
  - `USE_OCR_FALLBACK = True`
  - `OCR_MIN_PAGE_CHARS = 50`
- `requirements.txt` — add `easyocr>=1.7`.

### Smoke test (mandatory)

OCR can't be tested via the hard eval (no scanned PDFs in corpus). Manual smoke test required:

1. Generate a known image-only PDF (or drop one in): `sources/_test_ocr/sample.pdf`.
2. `python rag.py ingest sources/_test_ocr/sample.pdf --project test`
3. `python rag.py query "<known content from the PDF>" --project test`
4. Verify the OCR'd text appears in the retrieved chunks. Log line "OCR fallback engaged" should appear at INFO level.

### Verification

- `python eval/run.py` and `--hard` — no regression.
- Smoke test passes.

---

## Phase 7 — Smoke tests (30-45 min)

**Why last.** Covers the final shape of all backends and retrieval changes.

### Tests

`tests/test_smoke.py` (using pytest):

- `test_ingest_pdf_pymupdf` — ingest a known PDF, assert chunks created.
- `test_ingest_docx` — ingest a known DOCX, assert chunks.
- `test_ingest_xlsx` — ingest the financial template, assert chunks.
- `test_ingest_idempotent` — ingest same file twice, assert second ingest is cached (Phase 3).
- `test_hybrid_search_returns_results` — given an ingested corpus, `hybrid_search` returns ≥1 chunk.
- `test_min_per_source_quota` — ingest two sources with multiple chunks each, verify quota gives ≥2 from each in top-K.
- `test_hyde_skipped_for_short_query` — `should_use_hyde("find foo")` returns False; `should_use_hyde("how does break-even analysis work")` returns True.
- `test_project_filter` — ingest into two projects, verify queries scoped by `--project` only return from one.
- `test_eval_run_easy` — run `python eval/run.py`, assert exit 0 and 20/20.

`pytest.ini` for pytest config. New `requirements-dev.txt` for `pytest`.

### Verification

`python -m pytest tests/` → all green. The eval test is slow (~15 min); mark it `@pytest.mark.slow` so it can be excluded from quick runs (`pytest -m "not slow"`).

---

## Out of scope (explicitly)

- **Anthropic SDK + streaming generation.** User wants Claude Code CLI to stay on plan limits.
- **Web UI (FastAPI / Gradio).** Defer until corpus and use case justify.
- **marker-pdf.** docling chosen for table fidelity; revisit only if docling fails permanently.
- **Custom embeddings model swap.** BGE-M3 is staying.

---

## Time estimate

| Phase | Time |
|---|---|
| 0 — Multi-project isolation | 30-45 min |
| 1 — Hard eval expansion | 1.5-2 h |
| 2 — Logging + verbose | 1 h |
| 3 — Cache / idempotency | 45 min |
| 4 — HyDE | 2-3 h |
| 5 — docling chunker | 3-5 h |
| 5b — Ablation eval | 15 min |
| 6 — OCR fallback | 1-2 h |
| 7 — Smoke tests | 30-45 min |
| **Total** | **11-15 h** |

Plan as 2-3 working sessions:

- **Session 1 (~3.5-4.5 h):** Phases 0, 1, 2, 3.
- **Session 2 (~5.5-8 h):** Phases 4, 5, 5b.
- **Session 3 (~1.5-2.5 h):** Phases 6, 7.

The current 20/20 easy eval is the regression alarm at every step. Any phase that breaks it must be fixed before moving on.

---

## CLAUDE.md updates after the batch

Once Phases 0-7 land:

- Mark roadmap items 2-7 as done in the Roadmap section.
- Add **Project scoping** section explaining the `--project` flag and the `projects` subcommand.
- Add **Cache invalidation** subsection in Conventions: "When `CHUNKER_VERSION` or `EMBEDDING_MODEL` is changed in `config.py`, all source caches automatically invalidate on next ingest. Manual delete is unnecessary."
- Add **OCR fallback** to Known Limitations: "Per-page fallback when PyMuPDF returns less than 50 characters. Triggers easyocr; first run downloads ~500 MB of models."
- Update file table to include new modules: `claude_bridge.py`, `hyde.py`, `logging_setup.py`, `tests/`, `eval/questions_hard.json`.
- Note the docling install path used (3.12 venv if Fallback A) so future contributors can reproduce.
