"""Document parser. Handles PDF, DOCX, and XLSX; returns chunks ready for embedding.

The module is still named pdf_parser for backwards compatibility (pipeline.py
imports parse_pdf), but parse_pdf now dispatches to the right backend based on
file extension.

Backends
========
- PDF: docling (layout-aware, tables-as-markdown, headings preserved) when
  USE_DOCLING is True; otherwise PyMuPDF text-only.
- DOCX: python-docx, paragraphs grouped into ~3000-char synthetic pages.
- XLSX: openpyxl, one synthetic page per worksheet, rows pipe-delimited.

Chunking
========
`chunk_pages` is section-aware: when text contains markdown headings (`# `,
`## `, `### `), they are treated as preferred chunk boundaries. The chunker
falls back to paragraph boundaries when a section is too long.
"""

import hashlib
import logging

import fitz  # PyMuPDF
from pathlib import Path
from config import (
    CHUNK_SIZE_CHARS, CHUNK_OVERLAP_CHARS, MIN_CHUNK_CHARS,
    USE_DOCLING, USE_OCR_FALLBACK, OCR_MIN_PAGE_CHARS,
)

logger = logging.getLogger(__name__)

# Lazy module-level caches — initialize once per process.
_docling_converter = None
_easyocr_reader = None


def file_sha256(path: str | Path, chunk_size: int = 1 << 20) -> str:
    """SHA-256 of a file's bytes. Streams in 1 MB blocks to handle big PDFs."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk_size), b""):
            h.update(block)
    return h.hexdigest()


# ── Backends ─────────────────────────────────────────────────────────


def _get_docling_converter():
    """Lazy DocumentConverter singleton. First call downloads ~1 GB of models."""
    global _docling_converter
    if _docling_converter is None:
        from docling.document_converter import DocumentConverter
        logger.info("Initializing docling DocumentConverter (first-call may download models)...")
        _docling_converter = DocumentConverter()
    return _docling_converter


def _get_easyocr_reader():
    """Lazy easyocr.Reader singleton. First call downloads ~500 MB of detection +
    recognition models. English-only by default — adjust `langs` argument for
    other languages."""
    global _easyocr_reader
    if _easyocr_reader is None:
        import easyocr
        logger.info("Initializing easyocr Reader (first call downloads ~500MB)...")
        _easyocr_reader = easyocr.Reader(["en"], gpu=False, verbose=False)
    return _easyocr_reader


def _ocr_page(page) -> str:
    """OCR a single PyMuPDF page by rendering it to a PNG image at 200 DPI then
    feeding it to easyocr. Returns the OCR'd text (joined by spaces)."""
    reader = _get_easyocr_reader()
    pix = page.get_pixmap(dpi=200)
    img_bytes = pix.tobytes("png")
    # easyocr.readtext can take raw image bytes
    pieces = reader.readtext(img_bytes, detail=0, paragraph=True)
    return "\n\n".join(pieces).strip() if pieces else ""


def _extract_pdf_pages_pymupdf(pdf_path: str) -> list[dict]:
    """Plain text per page via PyMuPDF. When a page extracts less than
    OCR_MIN_PAGE_CHARS of text (typical for scanned PDFs) and USE_OCR_FALLBACK is
    on, OCR that single page via easyocr instead. The fallback is per-page so
    mixed PDFs (some text, some scanned) still get the cheap path where possible.
    """
    doc = fitz.open(pdf_path)
    pages = []
    for i, page in enumerate(doc):
        text = (page.get_text() or "").strip()
        if len(text) < OCR_MIN_PAGE_CHARS and USE_OCR_FALLBACK:
            logger.info(
                "OCR fallback engaged for %s page %d (%d chars from PyMuPDF)",
                pdf_path, i + 1, len(text),
            )
            try:
                ocr_text = _ocr_page(page)
                if ocr_text:
                    pages.append({"page_num": i + 1, "text": ocr_text})
                    continue
            except Exception as e:
                logger.warning("OCR failed on %s page %d: %s", pdf_path, i + 1, e)
        if text:
            pages.append({"page_num": i + 1, "text": text})
    doc.close()
    return pages


def _extract_pdf_pages_docling(pdf_path: str) -> list[dict]:
    """Layout-aware extraction via docling. Each page becomes one entry whose `text`
    is markdown — tables become `| col | col |` blocks, headings become `## H`,
    list items get `- ` bullets. The downstream section-aware chunker uses these.
    """
    conv = _get_docling_converter()
    result = conv.convert(pdf_path)
    doc = result.document

    pages = []
    for page_no in sorted(doc.pages.keys()):
        try:
            md = doc.export_to_markdown(page_no=page_no)
        except Exception as e:
            logger.warning("docling export failed for %s page %d: %s", pdf_path, page_no, e)
            md = ""
        if md and md.strip():
            pages.append({"page_num": page_no, "text": md.strip()})
    return pages


def _extract_pdf_pages(pdf_path: str) -> list[dict]:
    """Dispatch by config flag. Falls back to PyMuPDF if docling fails at runtime."""
    if USE_DOCLING:
        try:
            pages = _extract_pdf_pages_docling(pdf_path)
            if pages:
                return pages
            logger.warning("docling returned no pages for %s; falling back to PyMuPDF", pdf_path)
        except Exception as e:
            logger.warning("docling failed for %s (%s); falling back to PyMuPDF", pdf_path, e)
    return _extract_pdf_pages_pymupdf(pdf_path)


def _extract_docx_pages(docx_path: str) -> list[dict]:
    """DOCX has no real page concept in the data model. Group paragraphs into synthetic
    'pages' of ~3000 chars so citations still feel natural and chunking still works."""
    from docx import Document  # imported lazily so the dep is only required for .docx

    doc = Document(docx_path)

    blocks: list[str] = []
    for p in doc.paragraphs:
        if p.text.strip():
            blocks.append(p.text)
    for table in doc.tables:
        for row in table.rows:
            row_text = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
            if row_text:
                blocks.append(row_text)

    if not blocks:
        return []

    pages: list[dict] = []
    current: list[str] = []
    current_len = 0
    page_num = 1
    for block in blocks:
        if current_len + len(block) > 3000 and current:
            pages.append({"page_num": page_num, "text": "\n\n".join(current)})
            page_num += 1
            current = [block]
            current_len = len(block)
        else:
            current.append(block)
            current_len += len(block)
    if current:
        pages.append({"page_num": page_num, "text": "\n\n".join(current)})
    return pages


def _extract_xlsx_pages(xlsx_path: str) -> list[dict]:
    """One synthetic 'page' per worksheet. Each row is rendered as a pipe-delimited line
    so the LLM can see column structure. Empty rows and fully-empty cells are skipped.
    Formula cells render their cached computed value (data_only=True)."""
    from openpyxl import load_workbook  # lazy import

    wb = load_workbook(xlsx_path, data_only=True, read_only=True)

    pages: list[dict] = []
    page_num = 0
    for sheet in wb.worksheets:
        page_num += 1
        lines: list[str] = [f"Sheet: {sheet.title}"]
        for row in sheet.iter_rows(values_only=True):
            cells = [
                str(c).strip() if c is not None else ""
                for c in row
            ]
            if not any(cells):
                continue
            lines.append(" | ".join(cells))

        # Skip sheets with only the title line (no real data)
        if len(lines) <= 1:
            page_num -= 1
            continue

        pages.append({"page_num": page_num, "text": "\n".join(lines)})
    wb.close()
    return pages


# ── Public API ───────────────────────────────────────────────────────


SUPPORTED_EXTS = {".pdf", ".docx", ".xlsx"}


def extract_pages(path: str) -> list[dict]:
    """Dispatch to the right backend by file extension."""
    ext = Path(path).suffix.lower()
    if ext == ".pdf":
        pages = _extract_pdf_pages(path)
    elif ext == ".docx":
        pages = _extract_docx_pages(path)
    elif ext == ".xlsx":
        pages = _extract_xlsx_pages(path)
    else:
        raise ValueError(f"Unsupported file type: {ext}. Supported: {sorted(SUPPORTED_EXTS)}")

    if not pages:
        raise ValueError(
            f"No text extracted from {path}. "
            "If it's a scanned PDF, OCR is not yet supported."
        )
    return pages


def _split_units(text: str) -> list[tuple[str, str]]:
    """Split a page's text into (unit_kind, unit_text) tuples.

    Unit kinds:
      - "section"   — a markdown heading (one of `# `, `## `, `### `, `#### `)
      - "paragraph" — anything else, separated by blank lines
    Section units are preferred chunk boundaries; paragraph units are soft
    boundaries used when no section break is available within `chunk_size`.
    """
    units: list[tuple[str, str]] = []
    for block in text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        first_line = block.split("\n", 1)[0]
        if first_line.lstrip().startswith(("# ", "## ", "### ", "#### ")):
            units.append(("section", block))
        else:
            units.append(("paragraph", block))
    return units


def chunk_pages(
    pages: list[dict],
    source: str,
    chunk_size: int = CHUNK_SIZE_CHARS,
    overlap: int = CHUNK_OVERLAP_CHARS,
) -> list[dict]:
    """Split pages into overlapping chunks. Section-aware: if a markdown heading is
    encountered while accumulating a chunk, the chunk closes at that heading (so the
    new chunk starts with the section header). Falls back to paragraph boundaries
    inside long sections, matching the previous behavior."""
    units: list[tuple[str, str, int]] = []  # (kind, text, page_num)
    for page in pages:
        for kind, txt in _split_units(page["text"]):
            units.append((kind, txt, page["page_num"]))

    chunks = []
    i = 0
    while i < len(units):
        chunk_parts: list[str] = []
        chunk_pages: set[int] = set()
        start_i = i
        cur_len = 0

        # Take one unit at minimum (so we never produce an empty chunk)
        kind, txt, page_num = units[i]
        chunk_parts.append(txt)
        chunk_pages.add(page_num)
        cur_len += len(txt) + 2
        i += 1

        # Greedily pull more units while size permits and we don't cross a hard
        # section boundary. Section boundaries are honored only when the chunk has
        # already reached MIN_CHUNK_CHARS — otherwise we'd fragment short
        # sub-sections into tiny <100-char chunks that retrieve poorly.
        while i < len(units) and cur_len < chunk_size:
            kind, txt, page_num = units[i]
            if kind == "section" and cur_len >= MIN_CHUNK_CHARS:
                break
            if cur_len + len(txt) + 2 > chunk_size and chunk_parts:
                # Would exceed size — close chunk; let next chunk start here.
                break
            chunk_parts.append(txt)
            chunk_pages.add(page_num)
            cur_len += len(txt) + 2
            i += 1

        chunks.append({
            "chunk_id": len(chunks),
            "text": "\n\n".join(chunk_parts).strip(),
            "pages": sorted(chunk_pages),
            "source": source,
        })

        # Overlap: slide back so the next chunk shares the tail of this one. Skip
        # overlap when we just closed at a section boundary — section starts are
        # already natural, no need to duplicate.
        if i < len(units) and units[i][0] != "section":
            overlap_chars = 0
            j = i - 1
            while j > start_i and overlap_chars < overlap:
                overlap_chars += len(units[j][1])
                j -= 1
            i = j + 1

    return chunks


def parse_pdf(path: str) -> list[dict]:
    """Parse a PDF or DOCX into chunks. Name kept for backwards compatibility."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if p.suffix.lower() not in SUPPORTED_EXTS:
        raise ValueError(f"Unsupported file type: {p.suffix}. Supported: {sorted(SUPPORTED_EXTS)}")
    pages = extract_pages(str(p))
    return chunk_pages(pages, source=p.stem)


# Convenience alias for callers that want a clearer name
parse_document = parse_pdf
