#!/usr/bin/env python3
"""One-shot capstone deliverable generator.

Reads ingested capstone corpus from ChromaDB, sends to Claude Opus in a single
call with rubric-aware prompt, gets a complete markdown business plan, converts
to DOCX/PDF, then generates slides + XLSX fills via two more Sonnet calls.

Total runtime: ~15-25 minutes wall clock.
Total LLM calls: 3 (1 Opus + 2 Sonnet).

Output (in deliverables/):
    business_plan.md
    business_plan.docx
    business_plan.pdf
    presentation.pptx
    financial_model_filled.xlsx

Usage:
    python compose_capstone.py
"""

import sys
import os
import json
import re
import shutil
import subprocess
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from vectorstore import get_all_chunks
from config import CLAUDE_MODEL_QUALITY, CLAUDE_MODEL_FAST
from claude_bridge import call_claude
from groundedness import run_groundedness_check

PROJECT = "capstone"
ROOT = Path(__file__).parent
PROMPTS_DIR = ROOT / "prompts"
OUT_DIR = ROOT / "deliverables"
OUT_DIR.mkdir(parents=True, exist_ok=True)

TEMPLATE_XLSX = ROOT / "sources" / "capstone" / "Broadway_Cafe_Financial_Model_Template S26.xlsx"


def step(n, msg):
    print(f"\n{'=' * 60}\nStep {n}: {msg}\n{'=' * 60}", flush=True)


def dump_corpus(max_chars: int = 200_000):
    """Pull all chunks; if total exceeds max_chars, truncate PER SOURCE
    proportionally so every document contributes to the plan.

    The old implementation did a blind ``corpus[:max_chars]`` tail cut after
    sorting chunks by source name, so once the corpus exceeded the cap (the live
    capstone corpus is ~286K chars vs a 200K cap) the alphabetically-last sources
    contributed *nothing* to the business plan, and the groundedness gate — which
    verifies against the full corpus — could not detect the omission (finding F09).

    Now: each source gets a floor (so none is ever fully dropped) plus a share of
    the remaining budget proportional to its size, and the sources actually
    truncated are logged loudly. Set max_chars=None to disable truncation."""
    from collections import OrderedDict

    step(1, "Loading capstone corpus from ChromaDB")
    chunks = get_all_chunks(project=PROJECT)
    # Sort by `chunk_seq` (parser sequence number) for document order; fall back to
    # int(chunk_id) for legacy chunks where the ID was still numeric.
    def _seq_key(c):
        seq = c.get("chunk_seq")
        if seq is not None:
            try:
                return int(seq)
            except (TypeError, ValueError):
                pass
        cid = c.get("chunk_id")
        try:
            return int(cid) if cid is not None else 0
        except (TypeError, ValueError):
            return 0
    chunks.sort(key=lambda c: (c["source"], _seq_key(c)))

    # Group chunks by source, preserving document order within each.
    by_source: "OrderedDict[str, list[dict]]" = OrderedDict()
    for c in chunks:
        by_source.setdefault(c["source"], []).append(c)

    def _render_chunk(c):
        return f"\n[Pages {c['pages']}]\n{c['text']}\n"

    # Full (untruncated) text per source and its size.
    full_text_by_source = {
        src: "".join(_render_chunk(c) for c in cs) for src, cs in by_source.items()
    }
    size_by_source = {src: len(t) for src, t in full_text_by_source.items()}
    header = "# CAPSTONE REFERENCE MATERIAL\n"
    raw_total = len(header) + sum(size_by_source.values())

    # Decide a per-source char budget.
    if max_chars is None or raw_total <= max_chars:
        budget = dict(size_by_source)  # everything fits
    else:
        n_src = len(by_source) or 1
        body_budget = max(0, max_chars - len(header))
        # Every source is guaranteed at least FLOOR chars (or its full size if
        # smaller) so nothing is silently dropped.
        floor = min(3000, body_budget // n_src) if n_src else body_budget
        base = {src: min(size_by_source[src], floor) for src in by_source}
        used = sum(base.values())
        remaining = max(0, body_budget - used)
        unmet = {src: size_by_source[src] - base[src] for src in by_source}
        total_unmet = sum(unmet.values())
        budget = {}
        for src in by_source:
            extra = int(remaining * unmet[src] / total_unmet) if total_unmet else 0
            budget[src] = base[src] + min(extra, unmet[src])

    # Build the corpus honoring each source's budget; record truncation.
    parts = [header]
    truncated, dropped = [], []
    for src, cs in by_source.items():
        allotted = budget[src]
        body = full_text_by_source[src]
        marker = f"\n## Source: {src}\n"
        if allotted >= size_by_source[src]:
            parts.append(marker)
            parts.append(body)
        elif allotted <= 0:
            dropped.append(src)
            continue
        else:
            parts.append(marker)
            parts.append(body[:allotted])
            parts.append(f"\n[... {src} truncated: {allotted:,}/{size_by_source[src]:,} chars ...]\n")
            truncated.append((src, allotted, size_by_source[src]))

    corpus = "".join(parts)
    print(f"  {len(chunks)} chunks across {len(by_source)} sources, "
          f"{raw_total:,} raw chars; using {len(corpus):,} chars (~{len(corpus)//4:,} tokens)")
    if truncated:
        print(f"  WARNING: {len(truncated)} source(s) truncated proportionally to fit the {max_chars:,}-char cap:")
        for src, used_c, full_c in truncated:
            print(f"    - {src}: {used_c:,}/{full_c:,} chars ({used_c / full_c * 100:.0f}%)")
    if dropped:
        print(f"  WARNING: {len(dropped)} source(s) received zero budget and were DROPPED: {dropped}")
    return corpus


def dump_xlsx_structure():
    from openpyxl import load_workbook
    wb = load_workbook(TEMPLATE_XLSX, data_only=False, read_only=False)
    structure = {}
    for sheet in wb.worksheets:
        rows = []
        for row_idx, row in enumerate(sheet.iter_rows(values_only=False), 1):
            row_data = []
            for cell in row:
                if cell.value is None:
                    continue
                row_data.append({"cell": cell.coordinate, "value": str(cell.value)[:200]})
            if row_data:
                rows.append({"row": row_idx, "cells": row_data})
            if row_idx > 80:
                break
        structure[sheet.title] = rows
    wb.close()
    return json.dumps(structure, indent=2, ensure_ascii=False)


def _strip_code_fence(text):
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n", 1)
        text = lines[1] if len(lines) > 1 else ""
        if text.endswith("```"):
            text = text[:-3]
    return text.strip()


def generate_business_plan(corpus):
    step(2, "Generating business plan body (Opus, ~8-15 min)")
    template = (PROMPTS_DIR / "business_plan_prompt.txt").read_text(encoding="utf-8")
    full = template.replace("{{CORPUS}}", corpus)
    output = call_claude(CLAUDE_MODEL_QUALITY, "", full)
    md_path = OUT_DIR / "business_plan.md"
    md_path.write_text(output, encoding="utf-8")
    word_count = len(output.split())
    print(f"  Wrote {md_path.name} ({len(output):,} chars, ~{word_count:,} words)")
    return output


def convert_docx():
    step(3, "Converting markdown -> DOCX (pandoc)")
    md = OUT_DIR / "business_plan.md"
    docx = OUT_DIR / "business_plan.docx"
    if not shutil.which("pandoc"):
        print("  WARNING: pandoc not on PATH. Skipping DOCX.")
        print("  Install: winget install --id JohnMacFarlane.Pandoc")
        return None
    subprocess.run(
        ["pandoc", str(md), "-o", str(docx), "--toc", "--toc-depth=2",
         "--standalone", "-V", "geometry:margin=1in"],
        check=True,
    )
    print(f"  Wrote {docx.name}")
    return docx


def convert_pdf(docx_path):
    if docx_path is None:
        return None
    step(4, "Converting DOCX -> PDF")
    pdf = OUT_DIR / "business_plan.pdf"
    try:
        from docx2pdf import convert as d2p_convert
        d2p_convert(str(docx_path), str(pdf))
        if pdf.exists():
            print(f"  Wrote {pdf.name} via Word")
            return pdf
    except Exception as e:
        print(f"  docx2pdf failed: {e}")
    if shutil.which("soffice"):
        try:
            subprocess.run(
                ["soffice", "--headless", "--convert-to", "pdf",
                 "--outdir", str(OUT_DIR), str(docx_path)],
                check=True, capture_output=True,
            )
            print(f"  Wrote {pdf.name} via LibreOffice")
            return pdf
        except Exception as e:
            print(f"  LibreOffice failed: {e}")
    print("  WARNING: no PDF backend worked. Open business_plan.docx in Word, Save As PDF.")
    return None


def generate_slides(plan_md):
    step(5, "Generating slide deck JSON (Sonnet, ~2-4 min)")
    template = (PROMPTS_DIR / "slides_prompt.txt").read_text(encoding="utf-8")
    full = template.replace("{{BUSINESS_PLAN}}", plan_md)
    output = _strip_code_fence(call_claude(CLAUDE_MODEL_FAST, "", full))
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        # Try to extract JSON object from text
        m = re.search(r"\{.*\}", output, re.DOTALL)
        if m:
            data = json.loads(m.group(0))
        else:
            raise
    (OUT_DIR / "slides.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"  Generated {len(data.get('slides', []))} slides")
    return data


def render_pptx(slides_data):
    step(6, "Rendering PPTX")
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    for slide in slides_data["slides"]:
        kind = slide.get("kind", "content")
        if kind == "title":
            layout = prs.slide_layouts[0]
            s = prs.slides.add_slide(layout)
            s.shapes.title.text = slide.get("title", "")
            if len(s.placeholders) > 1:
                s.placeholders[1].text = slide.get("subtitle", "")
        else:
            layout = prs.slide_layouts[1]
            s = prs.slides.add_slide(layout)
            s.shapes.title.text = slide.get("title", "")
            body = s.placeholders[1].text_frame
            body.clear()
            bullets = slide.get("bullets", []) or []
            for j, b in enumerate(bullets):
                p = body.paragraphs[0] if j == 0 else body.add_paragraph()
                p.text = b
                p.level = 0
        notes = slide.get("notes", "")
        if notes:
            s.notes_slide.notes_text_frame.text = notes

    out = OUT_DIR / "presentation.pptx"
    prs.save(out)
    print(f"  Wrote {out.name} ({len(slides_data['slides'])} slides)")


def generate_xlsx_fills(plan_md):
    step(7, "Generating XLSX assumption fills (Sonnet, ~2-3 min)")
    if not TEMPLATE_XLSX.exists():
        print(f"  WARNING: template not found at {TEMPLATE_XLSX}. Skipping XLSX.")
        return None
    structure = dump_xlsx_structure()
    template = (PROMPTS_DIR / "xlsx_prompt.txt").read_text(encoding="utf-8")
    full = template.replace("{{BUSINESS_PLAN}}", plan_md).replace("{{XLSX_STRUCTURE}}", structure)
    output = _strip_code_fence(call_claude(CLAUDE_MODEL_FAST, "", full))
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", output, re.DOTALL)
        data = json.loads(m.group(0)) if m else {"fills": []}
    print(f"  Got {len(data.get('fills', []))} fills")
    return data


def apply_xlsx_fills(fills_data):
    if fills_data is None:
        return
    step(8, "Applying fills to XLSX template")
    from openpyxl import load_workbook
    out = OUT_DIR / "financial_model_filled.xlsx"
    shutil.copy(TEMPLATE_XLSX, out)
    wb = load_workbook(out, data_only=False)
    applied, skipped = 0, 0
    fills = fills_data.get("fills", [])
    for f in fills:
        sheet = f.get("sheet"); cell = f.get("cell"); value = f.get("value")
        if sheet not in wb.sheetnames:
            skipped += 1; continue
        ws = wb[sheet]
        try:
            existing = ws[cell].value
            # Don't overwrite formula cells (they start with =)
            if isinstance(existing, str) and existing.startswith("="):
                skipped += 1; continue
            ws[cell] = value
            applied += 1
        except Exception as e:
            print(f"  WARN failed {sheet}!{cell}: {e}"); skipped += 1
    wb.save(out)
    print(f"  Applied {applied}, skipped {skipped}, saved {out.name}")


def step_groundedness_gate(plan_md: str) -> bool:
    """Run G1 (extract+entail) and decide whether the deliverable can ship.

    Block rules (fail-closed, finding F05/F06):
      1. No claims extracted → FAIL (extraction failed / empty plan).
      2. >10% of claims errored during entailment → FAIL (verification incomplete,
         usually a CLI limit hit mid-gate; an all-ERROR run must not pass).
      3. Zero high-risk claims in a business plan → FAIL (the high-risk detector
         almost certainly missed the money sections).
      4. High-risk BLOCKING rate > 5% → FAIL, where blocking = UNSUPPORTED OR
         ERROR (unverifiable), and high-risk = section keyword match OR a claim
         carrying a currency/percentage/financial number (see
         ``groundedness._is_high_risk``).

    The full report lands in ``deliverables/groundedness_report.md`` regardless of
    the decision so the operator can review before re-running or shipping with
    ``--force-export``.
    """
    step("2.5", "Groundedness check (extract claims → entail → report)")
    summary = run_groundedness_check(plan_md, OUT_DIR, project=PROJECT)
    n = summary["n_claims"]
    if n == 0:
        # Either the plan was empty or extraction failed twice. Don't auto-pass.
        print("  Groundedness: no claims extracted — gate FAILED defensively.")
        return False

    n_err = summary.get("n_error", 0)
    n_hr = summary.get("n_high_risk_claims", 0)
    blocking_rate = summary.get("high_risk_blocking_rate", summary.get("high_risk_unsupported_rate", 0.0))
    print(
        f"  Groundedness: {summary['n_supported']}/{n} supported "
        f"({summary['unsupported_rate'] * 100:.1f}% unsupported, {n_err} ERROR/unverifiable)"
    )
    print(
        f"  High-risk: {summary.get('n_high_risk_unsupported', 0)} unsupported + "
        f"{summary.get('n_high_risk_error', 0)} unverifiable of {n_hr} "
        f"→ blocking rate {blocking_rate * 100:.1f}%"
    )

    # F05: an all-ERROR run (CLI plan limit hit mid-gate) would otherwise show 0
    # unsupported and pass. If more than 10% of claims failed to verify at all, the
    # verification itself is incomplete — refuse rather than ship unverified.
    if n_err > max(1, 0.10 * n):
        print(f"  GATE FAILED: {n_err}/{n} claims could not be verified (entailment errored).")
        print("  This usually means the Claude CLI hit an error/limit mid-gate. Re-run.")
        return False

    # F05/F06: zero high-risk claims in a business plan almost certainly means the
    # high-risk detector missed the money sections, not that there are none.
    if n_hr == 0:
        print("  GATE FAILED: no high-risk (financial) claims were identified in a "
              "business plan — the high-risk detector likely missed them. Review "
              "deliverables/groundedness_report.md before exporting.")
        return False

    if blocking_rate > 0.05:
        print("  GATE FAILED: high-risk unsupported/unverifiable rate > 5%.")
        print("  Review deliverables/groundedness_report.md before exporting PDF.")
        return False
    return True


def main():
    force_export = "--force-export" in sys.argv

    print("Capstone deliverable composer — single-shot generator")
    if force_export:
        print("  --force-export: groundedness gate will run but won't block.")
    corpus = dump_corpus()
    plan_md = generate_business_plan(corpus)

    gate_ok = step_groundedness_gate(plan_md)
    if not gate_ok and not force_export:
        print("\nAborting PDF/PPTX/XLSX generation. Fix unsupported claims first, "
              "then re-run; pass --force-export to bypass.")
        return

    docx = convert_docx()
    convert_pdf(docx)
    slides = generate_slides(plan_md)
    render_pptx(slides)
    fills = generate_xlsx_fills(plan_md)
    apply_xlsx_fills(fills)

    print("\n" + "=" * 60)
    print("DONE. Outputs in deliverables/:")
    for f in sorted(OUT_DIR.iterdir()):
        size = f.stat().st_size
        print(f"  {f.name:40s} {size:>10,} bytes")
    print("\nNext: open business_plan.docx in Word, voice/edit pass (~1-2h),")
    print("then submit business_plan.pdf and presentation.pptx to Brightspace.")


if __name__ == "__main__":
    main()
