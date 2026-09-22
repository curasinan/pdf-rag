# Full Picture

## What this is and what it is for

**PDF RAG Study Tool** is a local Retrieval-Augmented Generation pipeline built for one job: **studying from course material that is far too large to paste into an LLM's context window.** You ingest a folder of PDFs, DOCX and XLSX files once; after that you can ask questions, get topic lessons, generate quizzes, request summaries, or hold a chat session — and every answer is grounded in the ingested documents and carries page-level citations (`[source, p. X]`) you can verify against the original file.

It was built and battle-tested around a real business-school capstone corpus (24 documents, ~286K characters), where it also produced the final deliverables (business plan, slides, financial model) through a groundedness-gated composer. Generation runs through the Claude Code CLI on subscription plan limits by default — the pipeline is designed so that no call can silently fall through to metered API billing.

Use it when:

- your study material is hundreds of pages across many files and you need **answers with citations**, not vibes;
- you want **quizzes and lessons generated from your own corpus**, not the model's prior knowledge;
- you want a working, measured reference implementation of **hybrid retrieval** (dense + keyword + fusion + reranking) with an honest evaluation harness around it.

## How it works

One ChromaDB collection (BGE-M3, 1024-dim) plus a BM25 keyword index over the same chunks. A query runs both searches (50 candidates each, optionally a third HyDE channel), merges them with Reciprocal Rank Fusion (k=60), reranks the top 30 with a cross-encoder, and hands the top 10 chunks to Claude with a task-specific prompt. Citations are then checked twice: for fabrication (does the cited page exist and match?) and for attribution (does the cited chunk actually support the claim?). See `README.md` for commands and `CLAUDE.md` for the module-by-module reference.

## How it got here

The project was developed in phases; the working plans for those phases used to live in this repo and have been consolidated into this summary. Deep detail survives in `HISTORY.md`, `EVAL_NOTES.md`, and `ABLATION_NOTES.md` / `ABLATION_WRITEUP.md`.

1. **Foundation.** Parser (docling with PyMuPDF/OCR fallbacks), section-aware chunking, BGE-M3 embeddings, single-collection ChromaDB, BM25 + RRF hybrid retrieval, cross-encoder reranking, HyDE, project scoping, idempotent ingest.
2. **Evaluation contract.** A 20-question easy regression set, then a 25-question hard set (10 held out from all tuning), evidence-only LLM judges with multi-run medians, retrieval metrics (recall/MRR/nDCG), citation validation, per-query tracing, and a regression gate against a frozen baseline.
3. **Design review.** A 50-finding review; the top findings were fixed (gold-source resolution that raises instead of silently returning nothing, answer caching and per-question checkpointing so a session limit cannot destroy a run, output-naming discipline so a pilot can never be mistaken for a full run).
4. **Three-arm ablation.** Hybrid RAG vs whole-corpus-in-context vs agentic file access, 25 questions × 3 judge runs, paired statistics. Honest headline: no quality gap is statistically separable at n=25 (MDE ≈ 30pp); the hybrid arm was slowest and never better; its two losses are architectural (a retrieval miss and a chunking-granularity citation ceiling). Full report: `ABLATION_WRITEUP.md`.
5. **Judge hardening and freeze.** Every "carried-over critical error" turned out to be a judge false positive, not a system defect; the judge was fixed probe-first (planted defects must be caught before any fix ships), voting made span-aware and majority-based, and the baseline frozen: 24/25 EQUIVALENT, holdout 10/10 clean, regression gate green with zero warnings.
6. **Deliverable composer.** `compose_capstone.py` generates the capstone deliverables and gates them on claim-level groundedness. The gate's honest verdict is recorded in `EVAL_NOTES.md`: the submitted plan fails a 5% threshold largely because its own financial projections are unsupportable by any corpus — a threshold-design finding, not a fabrication finding.

## Where it stands

The pipeline is complete and frozen against its baseline; the remaining roadmap (promoting the attribution metric into the gate, splitting the groundedness gate by claim genre, demoting MRR/nDCG from answer-quality proxies) is tracked in `CLAUDE.md` § Roadmap.
