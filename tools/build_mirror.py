"""Build a plain-text mirror of the source corpus for the agentic arm (arm C).

Why a mirror is mandatory, not a convenience
============================================
Verified empirically on this machine: an agent pointed at ``sources/capstone``
reads **nothing**.

- ``Read`` on a PDF fails — it renders pages via ``pdftoppm``, which is not
  installed (poppler-utils). ``Read`` on .docx/.xlsx is rejected as binary.
- ``Grep`` on the PDFs is noise: body streams are Flate-compressed, so
  ``rg -i "table turn"`` — the literal ground-truth phrase for eval question
  h01, which appears on page 8 of the KPI document — returns **zero matches
  corpus-wide**, while the extracted text contains it.

So "point an agent at the folder" would measure poppler's absence, not
architecture. The mirror is built with :func:`pdf_parser.extract_pages`, the
*same* function ``parse_pdf`` calls before chunking, so arm A and arm C read
byte-identical source text. The only thing arm C loses relative to arm A is
chunking + embedding + BM25 + reranking — precisely the independent variable.
The only thing it gains is unrestricted access to all 24 documents, which is
what "agentic file search" means.

Deliberately NOT built from the stored chunks: chunks carry
``CHUNK_OVERLAP_CHARS`` of overlap and would duplicate content, and they would
bake arm A's chunk-boundary decisions into arm C.

Location
========
Defaults **outside the repo** (``%LOCALAPPDATA%/pdf-rag-ablation/corpus_mirror``).
A mirror inside ``data/`` would have the repo root as an ancestor, which means
the CLI's CLAUDE.md auto-discovery would pull in this project's rubric *and*
``eval/questions_hard.json`` — which contains the expected answer for every
question — into arm C's context. See ``eval/arms.py::_assert_sandbox``.

Usage
=====
    python tools/build_mirror.py                 # default location, verify on
    python tools/build_mirror.py --out DIR
    python tools/build_mirror.py --verify-only
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from config import DEFAULT_PROJECT                       # noqa: E402
from pdf_parser import extract_pages, SUPPORTED_EXTS     # noqa: E402
from vectorstore import get_all_chunks                   # noqa: E402


PAGE_MARKER = "=== PAGE {n} ==="
SOURCE_HEADER = "# SOURCE: {source}"
MANIFEST_NAME = "_manifest.json"
INDEX_NAME = "_INDEX.md"


def default_mirror_dir() -> Path:
    """A mirror location that is outside the repo *and* stable across shells.

    Not ``%LOCALAPPDATA%``: on this machine the Claude desktop app is an MSIX
    package, so a process running inside the app container has
    ``C:/Users/<u>/AppData/Local`` transparently redirected to
    ``…/AppData/Local/Packages/Claude_*/LocalCache/Local``. A mirror built from
    inside the app would then be invisible to a plain terminal — and arm C
    *must* be run from a plain terminal, because a ``claude`` subprocess spawned
    inside a Claude Code session cannot authenticate. Same literal path, two
    different physical directories, silent empty corpus.

    A sibling of the repo has neither problem: outside the repo (so the CLI
    cannot auto-discover this project's CLAUDE.md or ``eval/questions_hard.json``)
    and never virtualized.
    """
    return ROOT.parent / "pdf-rag-ablation" / "corpus_mirror"


def is_redirected(path: Path) -> bool:
    """True if the OS silently maps this path somewhere else (MSIX/UWP container).

    A redirected mirror path resolves differently depending on which shell built
    it, which is the difference between arm C reading 24 documents and reading
    nothing.
    """
    p = Path(path)
    try:
        return str(p.absolute()) != str(p.resolve())
    except OSError:
        return False


def slugify(name: str) -> str:
    """ASCII slug for a source stem.

    Five of the 24 filenames are hostile to round-tripping: one is NFD
    (``5 KPIs …Café…``), one starts with an emoji, one ends in U+2026, and two
    carry smart quotes. An agent that reads a name from a directory listing and
    retypes it will silently miss the NFD one. ASCII slugs remove that whole
    class of failure; the canonical name lives in the ``# SOURCE:`` header,
    which is what the agent must cite.
    """
    decomposed = unicodedata.normalize("NFKD", name)
    ascii_only = decomposed.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^A-Za-z0-9]+", "-", ascii_only).strip("-").lower()
    return slug or "source"


def render_document(source: str, pages: list[dict]) -> str:
    out = [SOURCE_HEADER.format(source=source), ""]
    for p in pages:
        out.append(PAGE_MARKER.format(n=p["page_num"]))
        out.append((p.get("text") or "").strip())
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def build(out_dir: Path, sources_dir: Path, project: str) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(
        p for p in sources_dir.iterdir()
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS
    )
    if not files:
        raise SystemExit(f"no supported source files under {sources_dir}")

    manifest, used_slugs = {}, {}
    for i, path in enumerate(files, 1):
        source = path.stem                      # matches pdf_parser.parse_pdf's source=p.stem
        print(f"[{i:>2}/{len(files)}] {source[:60]}")
        pages = extract_pages(str(path))

        slug = slugify(source)
        if slug in used_slugs:                  # distinct sources must not collide
            slug = f"{slug}-{len(used_slugs)}"
        used_slugs[slug] = source

        body = render_document(source, pages)
        (out_dir / f"{slug}.txt").write_text(body, encoding="utf-8")
        manifest[slug] = {
            "source": source,
            "source_nfc": unicodedata.normalize("NFC", source),
            "file": path.name,
            "n_pages": len(pages),
            "chars": len(body),
            "sha1": hashlib.sha1(body.encode("utf-8")).hexdigest(),
        }

    (out_dir / MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    index = [
        "# Corpus index",
        "",
        "One file per source document. Each begins with `# SOURCE: <canonical name>`;",
        "pages are delimited by `=== PAGE N ===`. Cite using the canonical name from",
        "the `# SOURCE:` header and the page number of the block the text came from.",
        "",
        "| file | source | pages |",
        "|---|---|---|",
    ]
    for slug, m in sorted(manifest.items()):
        index.append(f"| {slug}.txt | {m['source']} | {m['n_pages']} |")
    (out_dir / INDEX_NAME).write_text("\n".join(index) + "\n", encoding="utf-8")

    return manifest


def verify(out_dir: Path, project: str) -> int:
    """Assert the mirror contains what the vectorstore contains.

    If a stored chunk's text is not present in the mirror, arm A and arm C are
    reading different corpora and the "extraction held constant" claim — the
    whole basis for comparing them — is void.
    """
    manifest_path = out_dir / MANIFEST_NAME
    if not manifest_path.exists():
        print(f"FAIL: no {MANIFEST_NAME} in {out_dir}")
        return 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    by_source_nfc = {m["source_nfc"]: slug for slug, m in manifest.items()}
    texts = {
        slug: (out_dir / f"{slug}.txt").read_text(encoding="utf-8")
        for slug in manifest
    }

    chunks = get_all_chunks(project=project)
    if not chunks:
        print(f"FAIL: no chunks in project {project!r} to verify against")
        return 1

    def norm(s: str) -> str:
        return re.sub(r"\s+", " ", unicodedata.normalize("NFC", s)).strip()

    def mirror_body(text: str) -> str:
        """Mirror text with the header and page markers removed.

        A chunk is page units joined with "\\n\\n" and can span page boundaries,
        so it is only a contiguous substring of the mirror once the interleaved
        ``=== PAGE N ===`` lines are stripped out.
        """
        without_markers = re.sub(r"^={3} PAGE \d+ ={3}$", "", text, flags=re.MULTILINE)
        without_header = re.sub(r"^# SOURCE: .*$", "", without_markers, flags=re.MULTILINE)
        return norm(without_header)

    normed = {slug: mirror_body(t) for slug, t in texts.items()}

    missing_src, missing_txt = set(), []
    for c in chunks:
        src_nfc = unicodedata.normalize("NFC", c["source"])
        slug = by_source_nfc.get(src_nfc)
        if slug is None:
            missing_src.add(c["source"])
            continue
        probe = norm(c["text"])
        if len(probe) < 40:
            continue                                   # too short to be meaningful
        if probe not in normed[slug]:
            missing_txt.append((c["source"], c.get("pages"), probe[:70]))

    n_docs = len(manifest)
    n_pages = sum(m["n_pages"] for m in manifest.values())
    print(f"\nMirror: {n_docs} documents, {n_pages} pages, {out_dir}")
    print(f"Chunks checked: {len(chunks)} (project={project})")

    if missing_src:
        print(f"FAIL: {len(missing_src)} stored source(s) absent from the mirror:")
        for s in sorted(missing_src):
            print(f"  - {s}")
        return 1
    if missing_txt:
        print(f"FAIL: {len(missing_txt)} chunk(s) whose text is not in the mirror:")
        for src, pages, frag in missing_txt[:10]:
            print(f"  - {src} pages={pages}: {frag!r}")
        return 1

    print("OK: every stored chunk's text is present in the mirror "
          "(arm A and arm C read the same corpus).")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=None, help="Mirror directory (default: outside the repo).")
    ap.add_argument("--sources", default=str(ROOT / "sources" / "capstone"))
    ap.add_argument("--project", default="capstone")
    ap.add_argument("--verify-only", action="store_true")
    args = ap.parse_args()

    out_dir = Path(args.out) if args.out else default_mirror_dir()

    try:
        out_dir.resolve().relative_to(ROOT.resolve())
    except ValueError:
        pass          # good: outside the repo
    else:
        print(
            f"REFUSING: mirror {out_dir} is inside the repo.\n"
            "  The CLI auto-discovers CLAUDE.md from cwd and ancestors, and this repo\n"
            "  holds both the eval rubric and eval/questions_hard.json (every gold\n"
            "  answer). Build the mirror outside the repo."
        )
        return 1

    if is_redirected(out_dir):
        print(
            f"REFUSING: {out_dir}\n"
            f"  is redirected by the OS to {out_dir.resolve()}\n"
            "  (MSIX/UWP app-container virtualization). A mirror written here is\n"
            "  invisible to a plain terminal, and arm C must run from a plain\n"
            "  terminal because a `claude` subprocess started inside a Claude Code\n"
            "  session cannot authenticate. Pass --out with a non-virtualized path."
        )
        return 1

    print(f"Mirror location: {out_dir}")
    if not args.verify_only:
        build(out_dir, Path(args.sources), args.project)
    return verify(out_dir, args.project)


if __name__ == "__main__":
    raise SystemExit(main())
