# Capstone Deliverable Pipeline — Build Plan

## Goal

Extend the pipeline so a single command produces all capstone deliverables from the `capstone` corpus:

- `business_plan.docx` — 12-section Word document, MLA citations, ~5000-8000 words.
- `business_plan.pdf` — automatic conversion of the DOCX above (Brightspace requires PDF for the business plan; user submits this file).
- `presentation.pptx` — 10-12 slides matching the rubric outline, with speaker notes.
- `financial_model_filled.xlsx` — `Broadway_Cafe_Financial_Model_Template S26.xlsx` with assumption cells filled.

Final usage:

```
python rag.py compose --spec templates/capstone.yaml --project capstone --out deliverables/
```

The architecture is generic (spec-driven YAML), so future projects can reuse the same infrastructure with their own templates.

## Status check

Pipeline today: hybrid retrieval + Claude generation, output to stdout only. No file writers, no multi-section orchestration, no slide generation, no XLSX modification, no auto-citation, no AI use disclosure.

Time budget honest: this plan is 8-12 hours of dev work. Capstone is due Apr 30 23:59 local (about 24 hours from now). Build sequence is structured so Phases 1-3 alone produce a usable MVP (DOCX only) in 4-6 hours; remaining phases polish the result. If Phase 5 isn't done by hour 8, ship the MVP and manually polish the rest.

## Architecture overview

Spec-driven compose. The orchestrator takes a YAML spec describing sections / slides / cells, runs the existing `hybrid_search` for each unit's queries, generates content via Claude (Opus for body sections, Sonnet for short slide bullets), assembles into the target format using small writer modules. No new ML model dependencies; all heavy lifting reuses existing pipeline components.

Four writer modules:
- `writers/docx_writer.py` — `python-docx` based; supports H1-H4, paragraphs, bullets/numbered lists, tables (markdown → table), inline citations, bibliography.
- `writers/pdf_writer.py` — thin wrapper around `docx2pdf.convert(in, out)`. Uses Microsoft Word automation on Windows (no extra binary required if Office is installed). Falls back to LibreOffice headless mode if Word isn't found. Triggered automatically after DOCX is written so a single compose command produces both formats.
- `writers/pptx_writer.py` — `python-pptx` based; title slide, content slides (title + bullets + speaker notes), simple table slide, optional image slide.
- `writers/xlsx_writer.py` — `openpyxl` based; reads cell-fill plan, writes values into named cells, preserves formulas in dependent cells via `data_only=False` reload.

One spec format covers all three deliverables under one top-level YAML; the orchestrator routes each unit to the right writer.

## Phases

### Phase 1 — Writer modules (3-4 h)

Files:
- `writers/__init__.py`
- `writers/docx_writer.py` — class `DocxWriter`, methods `add_title_page`, `add_heading(level, text)`, `add_paragraph(text, citations=None)`, `add_bullets(items)`, `add_table(headers, rows)`, `add_bibliography(citations)`, `save(path)`.
- `writers/pdf_writer.py` — function `docx_to_pdf(docx_path, pdf_path)`. Tries `docx2pdf.convert` first (Word automation on Windows). On failure, falls back to `subprocess.run(['soffice', '--headless', '--convert-to', 'pdf', docx_path])` if LibreOffice is on PATH. Logs which backend was used. Raises if neither works so the user can run the manual Word "Save As PDF" step.
- `writers/pptx_writer.py` — class `PptxWriter`, methods `add_title_slide`, `add_content_slide(title, bullets, notes)`, `add_table_slide(title, headers, rows, notes)`, `add_image_slide(title, image_path, caption)`, `save(path)`.
- `writers/xlsx_writer.py` — function `apply_fills(template_path, fills, out_path)`. `fills` is a dict mapping `(sheet, cell_ref) -> value`. Loads workbook with `data_only=False` to keep formulas live, writes values, saves. Caller is responsible for not overwriting formula cells.

Verification:
- Four smoke tests in `tests/test_writers.py`: docx, pptx, xlsx each produce a non-empty file that opens cleanly. PDF test is conditional: skipped if neither Word nor LibreOffice is available, otherwise asserts the PDF file is created and >10KB.

Adds to `requirements.txt`: `python-pptx>=1.0.0`, `docx2pdf>=0.1.8`. `python-docx` and `openpyxl` already present.

### Phase 2 — Spec schema + loader (1-2 h)

Files:
- `compose_spec.py` — dataclasses for the spec, YAML loader with schema validation.

Schema:

```yaml
project: capstone           # which project to retrieve from
output_dir: deliverables/
team:
  group: "Section 91 Group 21"
  course: "MIS 311 — Information Systems & Applications, Spring 2026"
  members:
    - "Sinan Cura"
    - "Mert Palacios Bojalil"
    - "Mehmet Emir Ocal"
    - "Esra Gurses"
    - "Emre Erbek"

deliverables:
  - kind: docx
    out: business_plan.docx
    title: "The Broadway Café — Modernization Business Plan"
    # authors and group pulled from `team` block above; auto-rendered on title page
    citation_style: mla
    sections:
      - id: executive_summary
        heading: "1. Executive Summary"
        target_words: 350
        queries:
          - "vision and mission for coffee shop modernization"
          - "investment proposition and value creation drivers"
        instructions: |
          Executive overview. Cover modernization vision (customer experience,
          efficiency, data-driven decision making), strategy summary, capital
          requested, fund allocation, value creation logic. Executive tone.
          Cite material inline.
      # ... 12 sections total
    appendix:
      - kind: ai_use_disclosure
      - kind: bibliography

  - kind: pptx
    out: presentation.pptx
    slides:
      - kind: title
        title: "The Broadway Café — Modernization Plan"
        # subtitle auto-filled from team.course; team member names listed
        # below the subtitle in 4-name + lead-author layout
        subtitle_from_team: true
      - kind: content
        title: "Vision & Mission"
        target_bullets: 4
        queries: ["vision mission coffee shop modernization"]
        instructions: "4 punchy bullets covering modernization vision and mission. Speaker notes 50-80 words."
      # ... 10-12 slides

  - kind: xlsx
    template: sources/capstone/Broadway_Cafe_Financial_Model_Template S26.xlsx
    out: financial_model_filled.xlsx
    fills:
      - sheet: "Assumptions"
        cell: B5
        derive_from_query: "what is the assumed revenue decline rate 2023-2025"
        cast: float
      # ... per-cell fill plan
```

Validation: required fields present, queries non-empty, target_words reasonable, citation_style ∈ {mla, apa, none}.

### Phase 3 — Compose orchestrator (2-3 h)

Files:
- `compose.py` — new module exporting `compose(spec_path, project, out_dir)`.
- `pipeline.py` — wire `compose` into the public command surface.
- `rag.py` — new `compose` subcommand with `--spec`, `--project`, `--out`.

Per-section logic:

```python
def _build_section(section, project, citations):
    # 1. Retrieve: union of chunks from each query
    chunks = []
    seen = set()
    for q in section.queries:
        for c in hybrid_search(q, top_k=12, project=project):
            if c["id"] not in seen:
                chunks.append(c); seen.add(c["id"])
    # 2. Trim to context budget
    context = _format_context(chunks)[:MAX_CONTEXT_CHARS]
    # 3. Generate
    body = call_claude(
        CLAUDE_MODEL_QUALITY,
        SECTION_SYSTEM,
        SECTION_USER.format(
            heading=section.heading,
            target_words=section.target_words,
            instructions=section.instructions,
            context=context,
        ),
    )
    # 4. Collect citations from chunks actually present in body (substring match
    #    on source name, page nums) and append to global citation list.
    section_citations = _extract_citations(body, chunks)
    citations.extend(section_citations)
    return body, section_citations
```

For PPTX slides: same flow but with `SLIDE_SYSTEM` / `SLIDE_USER` prompts targeting bullet output (JSON: `{title, bullets: [...], notes: "..."}`).

For XLSX cells: each fill query returns a single answer, parsed via `cast` (`float`, `int`, `percent`, `text`) before writing.

Section ordering, slide ordering, and cell ordering is preserved from spec.

New prompts in `prompts.py`:
- `SECTION_SYSTEM`, `SECTION_USER` — body section generation with strict instruction following + inline citation directive.
- `SLIDE_SYSTEM`, `SLIDE_USER` — JSON-output bullet generation.
- `CELL_SYSTEM`, `CELL_USER` — single-value extraction with cast hint.

### Phase 4 — Capstone template (2-3 h)

Files:
- `templates/capstone.yaml` — top-level spec referencing the three sub-specs.
- `templates/capstone_business_plan.yaml` — 12 sections aligned to rubric (Executive Summary 0.5, Company Description 0.5, Market Analysis 1, Marketing Strategy 1, Products & Services 1, Location & Layout 0.5, Management 0.5, Operations 0.5, Technology 4, Financial 3, Funding Request 0.5, Risk Analysis 0.5, Appendix 0.5 = 14 pts).
- `templates/capstone_presentation.yaml` — 10 slides matching the rubric outline (Title, Vision/Mission, Modernization Strategies, Market Opportunity, Tech Integration, Operational Improvements, Phased Roadmap, Financial+CSF/KPI, Risks/Mitigation/Investment, Capstone Reflection).
- `templates/capstone_financial_model.yaml` — fill plan for the XLSX template's assumption cells (revenue trends, cost structure, growth rates).

Each section's `queries` and `instructions` are crafted to extract the right material from the 24 capstone sources. Specifically, key queries to design:
- Executive: "modernization vision investment thesis Broadway Café"
- Market analysis: "target customer segments competitors industry trends digital transformation"
- Tech plan: "ERP integration AI blockchain POS contactless payments cybersecurity master data management agentic AI workflow"
- Financial: "revenue decline 2023 2025 modernization forecast 2026 2030 break even"

Instructions for each section explicitly invoke rubric language ("Required framing: explain how competitors may use similar tech but fail due to weaker systems") so Claude generates content the rubric is calibrated to score well.

### Phase 5 — Citations + AI use disclosure (1 h)

Files:
- `citations.py` — `format_mla(source_name, pages) -> str`. Takes the chunk's `source` (filename stem) and `pages`, formats as MLA web-source style ("Author / Title. *Site*, Year. Web. p. X."). Since most sources lack author/year metadata, fall back to `Title. (n.d.). p. X.` template that's still rubric-compliant.
- AI use disclosure in `templates/capstone_business_plan.yaml` appendix — auto-generated section that lists: tools used (Claude Sonnet for generation, Claude Opus for synthesis), what was done (research synthesis from provided materials), what was NOT done (original analysis, strategic decisions, financial assumptions). Aligns with the `Appendix X AI Use Disclosure` form.

### Phase 6 — XLSX financial model fill (1-2 h)

XLSX is harder than DOCX because:
1. The template has formulas. Don't overwrite them.
2. Cell coordinates must be precise (B5 vs B6 fails silently).
3. Some cells need computed values (e.g., 2030 revenue = 2025 baseline × growth schedule), which Claude can produce but must be cast correctly.

Strategy:
- Open template in `data_only=False` mode (formulas preserved).
- Identify assumption cells (typically Assumptions sheet, rows for revenue/cost/headcount/growth).
- For each fill: generate value via the existing compose flow with `kind: xlsx_cell`.
- Save to `financial_model_filled.xlsx` in `out_dir`.

Phase 6 risk: if the template's exact cell layout doesn't match what we hardcode, fills land in wrong cells. Mitigation: before writing, dump the template's structure (sheet names, used ranges, named ranges) and build the fill plan by matching cell labels (column A) rather than fixed coordinates.

### Phase 7 — End-to-end test (30 min)

```
python rag.py compose --spec templates/capstone.yaml --project capstone --out deliverables/
```

Expected outputs:
- `deliverables/business_plan.docx` — 12 sections, 5000-8000 words, MLA citations, AI disclosure appendix.
- `deliverables/business_plan.pdf` — auto-converted from the DOCX above.
- `deliverables/presentation.pptx` — 10 slides with bullets and speaker notes.
- `deliverables/financial_model_filled.xlsx` — assumption cells filled.

Validation pass (manual, ~30 min):
1. Open DOCX, scan for empty sections, broken formatting, missing citations.
2. Open PDF, confirm it matches the DOCX content (no missing pages, no garbled tables).
3. Open PPTX, check slide count, bullet length, speaker notes presence.
4. Open XLSX, verify formulas still calculate correctly with new assumptions.

If `business_plan.pdf` was not produced (Word and LibreOffice both unavailable), open `business_plan.docx` in Word and use `File → Save As → PDF`. 30 seconds, drop in `deliverables/`.

## Out of scope

- True multi-agent orchestration (planner / writer / critic). Single-pass per section is good enough for MVP.
- Visual diagram generation (capability map, swim-lane, roadmap, heat map). User adds these manually in PowerPoint using SmartArt or pastes from Excalidraw.
- Style transfer ("write in my voice"). Tone is set by section instructions; manual editing handles voice.
- True Pandoc/Marp pipeline. We use python-docx + python-pptx directly to avoid external binary dependency.
- Turnitin pre-check. User submits and handles directly.

## Time estimate

Two paths. Pick one based on time budget.

### Full path (8-12 h) — generic, reusable across future projects

| Phase | Time | Cumulative |
|---|---|---|
| 1 — Writer modules (DOCX + PDF + PPTX + XLSX) | 3-4 h | 4 h |
| 2 — Spec schema with validation | 1-2 h | 6 h |
| 3 — Compose orchestrator + citation extraction | 2-3 h | 9 h |
| 4 — Capstone template (12 sections × 3 queries each) | 2-3 h | 12 h |
| 5 — Citations + AI disclosure | 1 h | 13 h |
| 6 — XLSX fill | 1-2 h | 15 h |
| 7 — End-to-end test | 0.5 h | 15.5 h |

This path produces infrastructure that any future project (CS-220, research, other classes) reuses by writing a new YAML template.

### MVP path (4-6 h) — capstone-only, simpler, throwaway-friendly

| Phase | Time |
|---|---|
| M1 — Minimal writers: DOCX (heading/para/bullet/table only), PDF wrap, PPTX (title + content slides only) | 2 h |
| M2 — Hardcoded `compose_capstone.py`: 12 sections inline, 10 slides inline, sequential generation | 1.5 h |
| M3 — Inline citations (just `[Source, p.X]` in body text) | 0.5 h |
| M4 — DOCX → PDF conversion via docx2pdf | 0.25 h |
| M5 — End-to-end test on capstone corpus | 0.75 h |

Total: 5 hours. Skips XLSX (manual fill), skips reusable templates, skips full MLA bibliography. Same Claude generation quality, less infrastructure.

### Where the 8-12 hours actually goes

- python-docx and python-pptx are verbose APIs. Each writer needs ~10 methods (headings, paragraphs, bullets, tables, images, citations, speaker notes). 30-45 minutes per backend, plus testing.
- Compose orchestrator's citation extraction is non-trivial: parse what Claude actually cited, match against retrieved chunks, build bibliography. ~1 hour of careful logic.
- Capstone template's 12 sections need rubric-aware queries and 100+ word instructions per section. Generic queries produce generic output.
- Full XLSX fill: parse template structure, identify assumption vs formula cells, map fills without breaking formula dependencies. 1-2 hours.
- Smoke tests, error handling, logging integration. ~1 hour spread across phases.

### Recommendation

**MVP path.** With 24 hours to deadline, 5h dev + 2h polish + 1h submission process leaves a 16-hour buffer for surprises. The reusability you give up is recoverable later — refactor MVP into generic compose.py over a weekend after submission.

User-facing command for MVP: `python rag.py compose-capstone --project capstone --out deliverables/`

## Single-prompt usage after implementation

After Claude Code completes the plan, the user runs:

```
python rag.py compose --spec templates/capstone.yaml --project capstone --out deliverables/
```

This produces `deliverables/business_plan.docx`, `deliverables/business_plan.pdf` (auto-converted), `deliverables/presentation.pptx`, and `deliverables/financial_model_filled.xlsx`. User opens each, makes voice / formatting passes (~1-2 h), submits the PDF and PPTX to Brightspace.

## Critical files

To create:
- `writers/__init__.py`
- `writers/docx_writer.py`
- `writers/pdf_writer.py`
- `writers/pptx_writer.py`
- `writers/xlsx_writer.py`
- `compose.py`
- `compose_spec.py`
- `citations.py`
- `templates/capstone.yaml`
- `templates/capstone_business_plan.yaml`
- `templates/capstone_presentation.yaml`
- `templates/capstone_financial_model.yaml`
- `tests/test_writers.py`

To modify:
- `pipeline.py` — expose `compose`.
- `rag.py` — new subcommand.
- `prompts.py` — `SECTION_SYSTEM`, `SECTION_USER`, `SLIDE_SYSTEM`, `SLIDE_USER`, `CELL_SYSTEM`, `CELL_USER`.
- `requirements.txt` — add `python-pptx>=1.0.0`, `docx2pdf>=0.1.8`, `pyyaml>=6.0`.
- `CLAUDE.md` — document the new compose subcommand and template format under "How to Run It".

## Failure modes to watch for

1. **Section generation hallucinates facts not in corpus.** Mitigation: section prompts include "if material doesn't cover this, state so explicitly" and the eval framework's negative-case judging style.
2. **Citations point to wrong pages.** Mitigation: post-generation verification — after Claude produces a section, parse out cited page numbers and check they exist in the retrieved chunks for that section. Strip invalid citations.
3. **PPTX bullets too long.** Mitigation: SLIDE_USER prompt enforces "≤ 12 words per bullet, ≤ 4 bullets per slide." Truncate at writer-level if Claude oversteps.
4. **XLSX cell coordinates wrong.** Mitigation: read template structure first, match by label not coordinate, log every fill before writing.
5. **MLA citation format incorrect.** Mitigation: `citations.format_mla` is unit-tested with 3-4 known examples covering web sources, no-author cases, and PDF documents.

## After capstone

Once submitted, the compose infrastructure is general. For future projects:
1. Ingest new sources to a new `--project`.
2. Write a new `templates/<project>.yaml` matching the project's deliverable shape.
3. Run `python rag.py compose ...` with the new spec.

The pipeline becomes a generic "structured-document generator from a corpus," not a one-off capstone tool.
