# PDF RAG Study Tool

A local RAG (Retrieval-Augmented Generation) pipeline for studying from documents that exceed an LLM's context window. Ingest PDFs, DOCX, and XLSX files into a vector store, then **query**, **summarize**, **teach**, **quiz**, or **chat** against the material — with page-level citations on every answer.

Generation runs through the Claude Code CLI by default (subscription plan limits, no metered API billing), with an optional Anthropic SDK backend behind a double opt-in.

## Architecture

```
                        INGEST                                RETRIEVE
 PDF/DOCX/XLSX ─▶ pdf_parser ─▶ section-aware ─┬─▶ BGE-M3 ─▶ ChromaDB ──┐
                 (docling +       chunker      │   (1024-d vectors)     │
                  PyMuPDF +                    └─▶ BM25 keyword index ──┤
                  OCR fallback)                                         ▼
                                                          Reciprocal Rank Fusion (k=60)
                                                                        │
                                                          cross-encoder rerank (top 30)
                                                                        │
                                                            top-10 context block
                                                                        ▼
                                                     Claude (CLI) ─▶ answer + [source, p. X]
```

Per-query flow:

1. Embed the query with **BGE-M3** (optionally augmented by **HyDE**: a short hypothetical answer whose embedding forms a third retrieval channel).
2. Pull 50 candidates from **ChromaDB** (cosine) and 50 from **BM25** (keywords).
3. Merge with **Reciprocal Rank Fusion**, rerank the top 30 with the **BAAI/bge-reranker-v2-m3** cross-encoder.
4. The top 10 chunks become the context block; answers must cite `[source, p. X]`.
5. Citations are validated for fabrication (`citations.py`) and claim attribution (`citation_support.py`).

All chunks live in a single ChromaDB collection with `source` / `project` metadata, so per-document and per-project scoping is a filter, not a separate index.

## Design decisions

- **Hybrid, not pure-dense.** BM25 catches the exact terms (names, numbers, acronyms) that embeddings fuzz over; RRF fuses the two rankings without score normalization because it is rank-based.
- **Cheap wide nets first, one expensive judge last.** The 50+50 candidate pulls cost milliseconds; the slow cross-encoder only ever sees 30 pairs. Measured: reranking rescues answers that fusion alone ranks just outside the window.
- **One collection, metadata scoping.** Per-document and per-project filters instead of per-document indexes, so query latency does not grow with corpus size.
- **Idempotent ingest.** Chunk IDs are content-addressed (`{project}::{source}::{sha1}`), so re-ingesting a file is a no-op and the same source can live in two projects.
- **A single choke point for LLM calls.** `claude_bridge.py` owns backend choice, billing safety (the CLI backend strips `ANTHROPIC_API_KEY` so nothing is silently metered), and token accounting.
- **Citations are verified, not trusted.** A fabrication check (cited page exists and matches) and a separate attribution check (cited chunk actually supports the claim) — the two are never conflated.
- **Evaluation is part of the pipeline.** A frozen baseline, a regression gate, held-out questions never tuned on, and planted-defect probes for the LLM judges themselves.

## Installation

```
python -m pip install -r requirements.txt
```

First runs download models that are then cached forever: BGE-M3 (~2.3 GB), the reranker (~600 MB), docling layout models (~1 GB), and easyocr (~500 MB, only if a scanned PDF triggers the OCR fallback).

## Usage

```
python rag.py ingest path/to/file.pdf          # single document
python batch_ingest.py path/to/folder          # bulk ingest, recursive

python rag.py list                             # what's in the store
python rag.py query "your question"
python rag.py query "..." --doc <source> --project <name>
python rag.py teach "topic"
python rag.py summarize --doc <source>
python rag.py quiz -n 10 --topic "topic"
python rag.py chat
python rag.py delete <source>
```

`<source>` is the filename without extension. `--verbose` / `-v` enables DEBUG retrieval logging.

## Evaluation

The pipeline ships with a full eval harness (`eval/`):

- 20-question easy regression set plus a 25-question hard set with per-source gold pages, required phrases, and expected numbers (10 questions held out from all tuning).
- LLM judges with evidence-only 5-axis scoring, multi-run medians, span-aware critical-error voting, and planted-defect probes (`tools/probe_judge.py`) that must pass after any judge edit.
- A regression gate (`eval/gate.py`) comparing runs against a frozen baseline — recall/MRR/nDCG tolerances plus blocking on *new* critical errors only.
- A three-arm ablation study (hybrid RAG vs whole-corpus context vs agentic file access) with paired statistics — see `ABLATION_WRITEUP.md`.

```
python -m pytest tests/ -m "not slow"          # 74 fast smoke tests
python eval/run.py --hard                      # full hard eval
python eval/gate.py --current eval/results_hard.json --baseline eval/baseline.json
```

## Repository map

| Area | Files |
|---|---|
| CLI + orchestration | `rag.py`, `pipeline.py`, `batch_ingest.py` |
| Parsing + chunking | `pdf_parser.py`, `config.py` |
| Retrieval | `retrieval.py`, `embeddings.py`, `vectorstore.py`, `bm25.py`, `reranker.py`, `hyde.py` |
| Generation | `claude_bridge.py`, `prompts.py` |
| Citation checks | `citations.py`, `citation_support.py`, `groundedness.py` |
| Eval harness | `eval/`, `tools/` |
| Documentation | `FULL_PICTURE.md` (what/why + project history), `ABLATION_WRITEUP.md` (retrieval-strategy study) |

## Notes

- Source documents and runtime data (`sources/`, `data/`) are not committed; the vector store and BM25 index are rebuilt by re-ingesting.
- OCR is fallback-only and per-page; DOCX/XLSX page numbers are synthetic.
- The default backend never touches a paid API key — `claude_bridge` strips `ANTHROPIC_API_KEY` from subprocess environments by design.
