"""One-shot bootstrap script: build eval/calibration.json from prior eval results.

Why this script exists
======================
B6 in WEEKEND_3_REMAINING.md asks for 50 calibration anchors (10 per question
type) with human labels. We have only 25 prior results across 5 types
(6+5+5+5+4), so a strict 10-per-type isn't achievable from existing data —
the spec's escape hatch ("relax the count") applies.

We also can't fabricate human labels. What we CAN do honestly:

1. Use the actual ``actual_answer``, ``expected_answer``, retrieval evidence,
   and recall computed by a prior eval. Those are real.
2. Derive the ``human_label`` from prior verdict + recall via a deterministic
   mapping documented below. Mark every anchor with
   ``bootstrap_method="prior_verdict_mapping"`` so any later reviewer knows
   the labels were not human-reviewed and can upgrade specific items.

Mapping (auditable, reproducible)
=================================
- relevance:
    EQUIVALENT      → 5
    PARTIAL         → 3
    DIFFERENT       → 1
    (anything else) → 1
- groundedness:
    if recall.applicable is False → 5  (negative questions: groundedness
        means "not asserting fabricated content"; the prior verdict already
        captured this)
    if source_full and pages_full  → 5
    if source_full and not pages_full → 4
    if not source_full              → 2
- citation_accuracy: starts at 5; downgrade to 3 if any retrieved doc was the
  required source but pages didn't match. For negative questions, always 5.
- critical_errors: empty unless verdict == DIFFERENT, in which case
  ["WRONG_EVIDENCE"].

Output
======
Writes ``eval/calibration.json``. Run once; subsequent edits are manual.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parent
PRIOR = ROOT / "results_v4_hyde_docling_hard.json"
OUT = ROOT / "calibration.json"


def _verdict_to_relevance(v: str) -> int:
    return {"EQUIVALENT": 5, "PARTIAL": 3, "DIFFERENT": 1}.get(v, 1)


def _label_groundedness(recall: dict, verdict: str) -> int:
    if not recall or not recall.get("applicable"):
        # Negative or non-cite question — groundedness is not directly testable
        # from recall. Trust the prior verdict.
        return 5 if verdict == "EQUIVALENT" else 3 if verdict == "PARTIAL" else 1
    if recall.get("source_full") and recall.get("pages_full"):
        return 5
    if recall.get("source_full"):
        return 4
    return 2


def _label_citation(recall: dict, verdict: str) -> int:
    if not recall or not recall.get("applicable"):
        return 5
    if recall.get("source_full") and recall.get("pages_full"):
        return 5
    if recall.get("source_full"):
        return 3
    return 2


def _evidence_chunks_from_retrieved(retrieved: list[dict]) -> list[dict]:
    """Trim the retrieved list to the schema the calibration harness will pass to
    the judge. We don't have the chunk text in the old result file, so we keep
    {source, pages} and let the harness re-resolve text via hybrid_search at
    judge time. This is documented in the calibration harness."""
    return [
        {"source": r.get("source"), "pages": r.get("pages")}
        for r in (retrieved or [])
    ]


def main():
    data = json.loads(PRIOR.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("results", [])

    counts: dict[str, int] = {}
    items = []
    for r in data:
        qtype = r.get("question_type", "qa")
        counts[qtype] = counts.get(qtype, 0) + 1
        seq = counts[qtype]
        verdict = r.get("verdict", "DIFFERENT")
        recall = r.get("recall", {}) or {}
        crit = ["WRONG_EVIDENCE"] if verdict == "DIFFERENT" else ["NONE"]
        items.append({
            "id": f"cal_{qtype}_{seq:02d}",
            "question_type": qtype,
            "question": r.get("question"),
            "expected_answer": r.get("expected_answer"),
            "candidate_answer": r.get("actual_answer"),
            "evidence_chunks": _evidence_chunks_from_retrieved(r.get("retrieved", [])),
            "recall_snapshot": recall,
            "must_cite_sources": r.get("must_cite_sources", []),
            "must_contain": r.get("must_contain", []),
            "expected_numbers": r.get("expected_numbers", []),
            "human_label": {
                "relevance": _verdict_to_relevance(verdict),
                "groundedness": _label_groundedness(recall, verdict),
                "citation_accuracy": _label_citation(recall, verdict),
                "critical_errors": crit,
            },
            "bootstrap_method": "prior_verdict_mapping",
            "notes": (
                f"Bootstrapped from {Path(PRIOR.name).name} verdict={verdict}. "
                "human_label derived deterministically; upgrade by manual review."
            ),
        })

    # Document the relaxation in a header object — not strictly part of the
    # array but the calibrate.py harness reads the file as either a list or a
    # {"items": [...]} envelope.
    payload = {
        "schema_version": 1,
        "source_file": PRIOR.name,
        "bootstrap_method": "prior_verdict_mapping",
        "anchor_counts": counts,
        "n_anchors": len(items),
        "limitation_note": (
            "B6 asked for 10 anchors per question_type (50 total). Prior eval "
            "has 25 results (6 page_lookup, 5 synthesis, 5 numeric, 5 qa, "
            "4 negative). We use all 25 and document the gap rather than "
            "fabricating extra anchors. Manually-reviewed labels are stronger "
            "than bootstrapped ones; upgrade individual items as you inspect them."
        ),
        "items": items,
    }
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {OUT.relative_to(ROOT.parent)}: {len(items)} anchors ({counts})")


if __name__ == "__main__":
    main()
