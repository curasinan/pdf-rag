"""Gold-passage resolution — the single owner of "which chunks are the ground
truth for this question".

Used by ``eval/oracle.py`` today and by the ablation harness's gold-evidence
judge mode. Deliberately depends only on ``vectorstore`` and ``citations`` so
that ``eval/run.py`` can import it without a cycle.

Why this module exists
======================
``must_cite_sources[].source`` in ``questions_hard.json`` is stored NFC.
ChromaDB stores whatever the filesystem handed the ingester, and for
``5 KPIs Every Clever Café Manager Should Track`` that is **NFD** (``e`` +
U+0301). ``vectorstore.get_chunks_for_source`` builds an *exact* Chroma
``where`` predicate, so the NFC name matched zero rows — silently.

Four gold entries were affected (h01, h05, h06, and one of h08's two sources),
which means ``eval/oracle.py`` has printed "gold source not in vectorstore
(deleted?) → skip" for those questions on every run it has ever done, and any
gold-evidence judging built on the old helper would have handed the judge an
empty EVIDENCE block for 12% of the hard set — two of them holdout questions.

Retrieval recall, MRR, nDCG and citation validation were never affected: they
NFC-normalize both sides (``eval/run.py::_nfc``, ``citations._normalize_source``).
Only the exact-match path was broken.

The fix is a normalized index over the *stored* source strings, so lookups are
encoding-insensitive in both directions. A named source that still fails to
resolve raises ``GoldSourceMissing`` rather than returning ``[]`` — a silent
empty gold set is precisely the failure mode that hid here for months.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from citations import _coerce_pages_field, _nfc          # noqa: E402
from config import DEFAULT_PROJECT                       # noqa: E402
from vectorstore import get_chunks_for_source, list_documents  # noqa: E402


class GoldSourceMissing(LookupError):
    """A question names a gold source that does not exist in the vectorstore.

    Raised instead of returning an empty gold set so a corpus/label mismatch
    fails loudly at eval time rather than silently degrading the reference
    evidence to nothing.
    """

    def __init__(self, source: str, project: str, known: list[str] | None = None):
        self.source = source
        self.project = project
        self.known = known or []
        hint = ""
        if self.known:
            hint = "\n  Ingested sources: " + "\n    ".join([""] + sorted(self.known))
        super().__init__(
            f"gold source {source!r} not found in project {project!r} "
            f"(tried exact and unicode-normalized match).{hint}"
        )


# ── Source resolution ────────────────────────────────────────────────

_SOURCE_INDEX: dict[str, dict[str, str]] = {}


def _source_index(project: str) -> dict[str, str]:
    """NFC(source) -> the exact stored source string, for one project.

    Cached per project because ``list_documents`` is a full-collection scan.
    Call :func:`invalidate_source_index` after any ingest or delete.
    """
    cached = _SOURCE_INDEX.get(project)
    if cached is None:
        cached = {_nfc(s): s for s in list_documents(project=project)}
        _SOURCE_INDEX[project] = cached
    return cached


def invalidate_source_index(project: str | None = None) -> None:
    """Drop the cached source index (after ingest / delete / re-ingest)."""
    if project is None:
        _SOURCE_INDEX.clear()
    else:
        _SOURCE_INDEX.pop(project, None)


def resolve_source(name: str, project: str = DEFAULT_PROJECT) -> str | None:
    """Return the stored spelling of ``name``, or None if it does not exist.

    Encoding-insensitive: an NFC label resolves an NFD-stored source and vice
    versa. Returns the *stored* string so callers can pass it straight to an
    exact-match ``where`` filter.
    """
    return _source_index(project).get(_nfc(name or ""))


# ── Gold chunk selection ─────────────────────────────────────────────


def gold_chunks_for_question(
    must_cite_sources: list[dict],
    project: str = DEFAULT_PROJECT,
) -> list[dict]:
    """Pull every chunk of every wanted source, keeping those whose page list
    overlaps the wanted pages (or all of them when no pages were specified).

    Returned in document order, de-duplicated by chunk id across sources.

    An empty ``must_cite_sources`` returns ``[]`` — that is legitimate for
    negative questions, which have no gold passage by construction. A *named*
    source that cannot be resolved raises :class:`GoldSourceMissing`.
    """
    out: list[dict] = []
    seen_ids: set[str] = set()

    for entry in must_cite_sources or []:
        name = entry["source"]
        stored = resolve_source(name, project)
        if stored is None:
            raise GoldSourceMissing(name, project, list(_source_index(project).values()))

        wanted_pages = entry.get("pages") or []
        for c in get_chunks_for_source(stored, project=project):
            cid = c.get("id")
            if cid is not None and cid in seen_ids:
                continue
            if wanted_pages:
                pages = _coerce_pages_field(c.get("pages"))
                if not any(p in wanted_pages for p in pages):
                    continue
            out.append(c)
            if cid is not None:
                seen_ids.add(cid)

    return out
