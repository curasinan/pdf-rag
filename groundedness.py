"""Groundedness gate for high-stakes deliverables (Weekend-3 Phase G1+G2).

Why this exists
===============
Chapter 6 §6.1 of the book treats unsupported high-stakes claims as critical
errors. `compose_capstone.py` writes ``business_plan.md`` from a single Opus
call against the entire corpus. Without claim-level verification, a fabricated
financial figure, a mis-attributed KPI, or an invented operational detail
shipping in the deliverable looks identical to a correctly grounded one. This
module is the asymmetric defense: cheap to run pre-export, catches the failure
mode that costs the most.

Pipeline
========
1. ``extract_claims`` splits the markdown plan into atomic factual claims
   (numbers, attributions, falsifiable assertions) — not framing sentences.
   The whole plan goes to Sonnet with a JSON-schema prompt and the same
   1-retry parsing pattern ``eval/run.py::_parse_judge_json`` uses.
2. ``entail_claim`` retrieves top-3 grounding chunks for each claim via the
   project's normal hybrid retrieval, then asks Sonnet whether the evidence
   supports / partially supports / contradicts the claim. JSON output again.
3. ``run_groundedness_check`` orchestrates the two and writes:
       output_dir/claims.json
       output_dir/entailment.json
       output_dir/groundedness_report.md
   It returns a summary dict the gate in ``compose_capstone.py`` reads.

High-risk claims
================
A claim is high-risk if its ``section`` name matches a high-risk keyword (a
broadened list including funding/capital/forecast/margin/ROI/…) OR the claim
text itself carries a currency/percentage/financial number — so a fabricated
figure in a "Funding Request" section is caught even though the heading has no
keyword (finding F06). The compose-time gate fails when the high-risk BLOCKING
rate — UNSUPPORTED *or* ERROR (unverifiable) — exceeds 5%, when zero high-risk
claims are found in a business plan, or when too many claims errored to trust
the verification (finding F05). Non-high-risk unsupported claims still appear in
the report but don't block export.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from config import CLAUDE_MODEL_FAST, CLAUDE_MODEL_QUALITY
from claude_bridge import call_claude, ClaudeCLIError
from retrieval import hybrid_search

logger = logging.getLogger(__name__)


# ── Constants ────────────────────────────────────────────────────────


# Broadened (finding F06): the old six-keyword list matched only sub-headings that
# literally said "Financial / Cost / Revenue / …", so the plan's real money
# sections — "Funding Request", "Capital Required", "Modernization Forecast",
# "Balance Sheets", "Investment Proposition" — escaped the high-risk gate entirely
# and could ship fabricated figures. We now also flag on funding/forecast/margin/
# ROI/etc. AND, crucially, on the claim TEXT: any claim carrying a currency or
# percentage token (or a large/decimal number) is high-risk regardless of its
# section name, because that is exactly the fabrication the gate exists to block.
HIGH_RISK_KEYWORDS = (
    "financial", "finance", "risk", "kpi", "cost", "revenue", "break-even",
    "break even", "funding", "fund", "capital", "forecast", "budget", "balance",
    "margin", "roi", "payback", "invest", "profit", "loss", "expense", "cash",
    "price", "pricing", "valuation", "projection", "assumption",
)
GROUNDING_TOP_K = 3

# Currency / percentage / financially-significant number tokens in a claim.
_HIGH_RISK_NUMBER_RE = re.compile(
    r"[$€£]\s?\d"                      # $57,000 / €1.2
    r"|\d+(?:\.\d+)?\s?%"              # 26% / 3.5 %
    r"|\b\d+(?:,\d{3})+(?:\.\d+)?\b"   # 822,800 (thousands-separated)
    r"|\b\d+\.\d+\b"                   # 1.5 / 0.28 (any decimal)
    r"|\b\d{4,}\b"                     # 57000 (4+ digit integer)
    r"|\b\d+(?:\.\d+)?\s?(?:percent|dollars?|usd|eur|gbp|%)\b",
    re.IGNORECASE,
)

CLAIM_EXTRACTION_SYSTEM = (
    "You extract atomic factual claims from a business plan markdown for "
    "evidence-based verification. A claim is something falsifiable against a "
    "source corpus: a number, a fact, an attribution, or an assertion of a "
    "relationship between things. Hedging language (\"we believe X may improve "
    "Y\") still counts as a claim because it asserts a relationship. Skip "
    "framing/transition sentences (\"This section discusses…\", \"In conclusion…\") "
    "and pure stylistic prose with no falsifiable content. Reply with a single "
    "JSON object, nothing else, no code fences, no preamble."
)

CLAIM_EXTRACTION_USER = """Business plan (markdown):

---
{plan}
---

Extract every atomic factual claim you find. For each claim, return:
- id: "c001", "c002", ... in document order, zero-padded to 3 digits.
- section: the closest preceding markdown heading (or "Preamble" before the first heading).
- claim: the claim, rewritten as a single declarative sentence in 5-30 words. Stay faithful to the original wording when possible.
- context: 2-3 surrounding sentences from the plan that contain the claim. Used for evidence retrieval.

Aim for 30-80 claims for a typical business plan. Skip transition sentences and pure framing.

Output exactly this JSON shape, nothing else:
{{"claims":[{{"id":"c001","section":"<heading>","claim":"<one sentence>","context":"<2-3 sentences>"}}, ...]}}"""

ENTAILMENT_SYSTEM = (
    "You decide whether a candidate claim is supported by the retrieved evidence. "
    "Use ONLY the evidence block — ignore your outside knowledge. SUPPORTED means "
    "the evidence directly states the claim's facts. PARTIALLY_SUPPORTED means the "
    "evidence supports part of the claim but not all of it (e.g. a number is "
    "right but the attribution is wrong, or the relationship is plausible but "
    "not asserted). UNSUPPORTED means the evidence does not contain the claim's "
    "core facts, or contradicts them. Reply with a single JSON object, no code "
    "fences, no preamble."
)

ENTAILMENT_USER = """Claim:
{claim}

Surrounding context from the plan:
{context}

Retrieved evidence (use ONLY this):
{evidence}

Output exactly this JSON shape:
{{"support":"SUPPORTED|PARTIALLY_SUPPORTED|UNSUPPORTED","evidence_chunk_ids":["..."],"rationale":"<one sentence>"}}"""


# ── JSON parsing (mirrors eval/run.py's _parse_judge_json behavior) ──


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("\n", 1)
        text = parts[1] if len(parts) > 1 else ""
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    return text


def _parse_json_with_recovery(raw: str) -> dict | None:
    """Best-effort JSON parse. Strips code fences, falls back to the first {...}
    block. Returns None on hard failure so callers can retry.

    This intentionally mirrors ``eval/run.py::_parse_judge_json``'s recovery
    pattern; we don't import that helper because it returns a different schema
    (5-axis judge dict) and validates fields we don't have here."""
    if not raw:
        return None
    text = _strip_code_fence(raw)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None


def _call_with_json_retry(
    model: str, system: str, user: str, retries: int = 1,
) -> dict | None:
    """Run a Claude CLI call expected to return JSON. ``retries`` re-runs of the
    same prompt are attempted on parse failure.

    Both claim extraction and entailment are verifier-style calls — we want
    determinism, not creativity — so we pass ``temperature=0.0``. Today the
    CLI ignores it (see ``claude_bridge.call_claude`` docstring), but the
    intent is recorded for the future SDK port."""
    for attempt in range(retries + 1):
        try:
            raw = call_claude(model, system, user, temperature=0.0)
        except ClaudeCLIError:
            return None
        parsed = _parse_json_with_recovery(raw)
        if parsed is not None:
            return parsed
        logger.warning(
            "groundedness JSON parse failed (attempt %d/%d); raw[:200]=%r",
            attempt + 1, retries + 1, (raw or "")[:200],
        )
    return None


# ── G1.1: claim extraction ───────────────────────────────────────────


@dataclass
class Claim:
    id: str
    section: str
    claim: str
    context: str

    def to_dict(self) -> dict:
        return asdict(self)


def extract_claims(business_plan_md: str, model: str = CLAUDE_MODEL_FAST) -> list[dict]:
    """Split a markdown plan into atomic factual claims via Sonnet + JSON.

    Returns a list of dicts with keys ``id``, ``section``, ``claim``, ``context``.
    Returns an empty list if the model fails to produce valid JSON twice.

    The prompt asks for 30-80 claims; we don't enforce a hard count because the
    plan length and density vary. The downstream entailment step is robust to
    any number — it just runs once per claim.
    """
    if not business_plan_md or not business_plan_md.strip():
        logger.warning("extract_claims: empty plan; returning no claims")
        return []
    user = CLAIM_EXTRACTION_USER.format(plan=business_plan_md)
    parsed = _call_with_json_retry(model, CLAIM_EXTRACTION_SYSTEM, user)
    if parsed is None:
        logger.error("extract_claims: claim-extraction call returned no valid JSON")
        return []
    raw_claims = parsed.get("claims") or []
    if not isinstance(raw_claims, list):
        logger.error("extract_claims: 'claims' key is not a list (got %s)", type(raw_claims).__name__)
        return []
    out: list[dict] = []
    for i, c in enumerate(raw_claims):
        if not isinstance(c, dict):
            continue
        claim_text = (c.get("claim") or "").strip()
        if not claim_text:
            continue
        out.append({
            "id": str(c.get("id") or f"c{i + 1:03d}"),
            "section": str(c.get("section") or "Unknown"),
            "claim": claim_text,
            "context": str(c.get("context") or claim_text),
        })
    logger.info("extract_claims: %d atomic claims extracted from %d-char plan",
                len(out), len(business_plan_md))
    return out


# ── G1.2: entailment ─────────────────────────────────────────────────


_VALID_SUPPORT = {"SUPPORTED", "PARTIALLY_SUPPORTED", "UNSUPPORTED"}


def _format_evidence(chunks: list[dict]) -> str:
    """Same shape as pipeline._format_context — keep the format consistent so
    the model sees the same evidence layout it does at QA time (pages rendered in
    human form so the header stays citation-parseable, finding F10)."""
    from citations import format_pages_human
    parts = []
    for c in chunks:
        source = c.get("source", "unknown")
        pages = format_pages_human(c.get("pages"))
        label = "page" if pages.isdigit() else "pages"
        parts.append(f"[{source}, {label} {pages}]\n{c.get('text', '')}")
    return "\n\n---\n\n".join(parts)


def entail_claim(
    claim: dict,
    retrieved_chunks: list[dict] | None = None,
    model: str = CLAUDE_MODEL_FAST,
    project: str = "capstone",
) -> dict:
    """Decide whether a single claim is supported by retrieved evidence.

    If ``retrieved_chunks`` is None, this function fetches the top-3 grounding
    chunks via ``hybrid_search``. Passing chunks in is supported for tests and
    for the calibration harness which may want to inject fixed evidence.

    Returns
    -------
    dict
        {
          "claim_id": str,
          "support": "SUPPORTED" | "PARTIALLY_SUPPORTED" | "UNSUPPORTED" | "ERROR",
          "evidence_chunk_ids": list[str],
          "rationale": str,
          "retrieved": [{"source", "pages", "id", "text_hash"}, ...],
        }
    """
    if retrieved_chunks is None:
        retrieved_chunks = hybrid_search(
            claim["claim"], top_k=GROUNDING_TOP_K, project=project,
        )

    # Build the trace records before LLM call so even an LLM failure path has
    # the retrieval evidence recorded.
    from tracing import hash_text
    retrieved_records = [
        {
            "source": c.get("source", "?"),
            "pages": c.get("pages"),
            "id": c.get("id") or c.get("chunk_id"),
            "text_hash": hash_text(c.get("text", "")),
        }
        for c in retrieved_chunks
    ]

    if not retrieved_chunks:
        return {
            "claim_id": claim["id"],
            "support": "UNSUPPORTED",
            "evidence_chunk_ids": [],
            "rationale": "No evidence retrieved for this claim.",
            "retrieved": retrieved_records,
        }

    user = ENTAILMENT_USER.format(
        claim=claim["claim"],
        context=claim.get("context", "") or claim["claim"],
        evidence=_format_evidence(retrieved_chunks),
    )
    parsed = _call_with_json_retry(model, ENTAILMENT_SYSTEM, user)
    if parsed is None:
        logger.error("entail_claim %s: entailment call returned no valid JSON", claim["id"])
        return {
            "claim_id": claim["id"],
            "support": "ERROR",
            "evidence_chunk_ids": [],
            "rationale": "Judge call failed to return parseable JSON.",
            "retrieved": retrieved_records,
        }

    raw_support = str(parsed.get("support", "")).upper().strip()
    if raw_support not in _VALID_SUPPORT:
        # Be lenient on common variants the model produces despite instructions
        if "UNSUPPORT" in raw_support:
            raw_support = "UNSUPPORTED"
        elif "PARTIAL" in raw_support:
            raw_support = "PARTIALLY_SUPPORTED"
        elif "SUPPORT" in raw_support:
            raw_support = "SUPPORTED"
        else:
            raw_support = "ERROR"

    evidence_ids = parsed.get("evidence_chunk_ids", []) or []
    if not isinstance(evidence_ids, list):
        evidence_ids = [str(evidence_ids)]
    evidence_ids = [str(e) for e in evidence_ids if e]

    return {
        "claim_id": claim["id"],
        "support": raw_support,
        "evidence_chunk_ids": evidence_ids,
        "rationale": str(parsed.get("rationale", "")).strip()[:300],
        "retrieved": retrieved_records,
    }


# ── G1.3: orchestration + report ─────────────────────────────────────


def _is_high_risk(section: str, claim: str = "") -> bool:
    """A claim is high-risk if its section name matches a high-risk keyword OR the
    claim text itself carries a currency/percentage/financially-significant number
    (finding F06). The section-only signature is kept working (``claim`` defaults
    to "") so existing callers and tests don't break."""
    s = (section or "").lower()
    if any(kw in s for kw in HIGH_RISK_KEYWORDS):
        return True
    if claim and _HIGH_RISK_NUMBER_RE.search(claim):
        return True
    return False


def _render_markdown_report(
    plan_path_label: str,
    claims: list[dict],
    entailments: list[dict],
    summary: dict,
) -> str:
    """Render a human-readable groundedness report. The structure here matches
    the spec in WEEKEND_3_REMAINING.md so the operator reading it knows where
    to look first."""
    by_id = {e["claim_id"]: e for e in entailments}
    n = summary["n_claims"]
    if n == 0:
        return "# Groundedness Report\n\n(no claims extracted)\n"

    lines = [
        "# Groundedness Report",
        "",
        f"Plan: {plan_path_label}",
        f"Total claims: {n}",
        f"Supported: {summary['n_supported']} ({summary['n_supported'] / n * 100:.1f}%)",
        f"Partially: {summary['n_partial']} ({summary['n_partial'] / n * 100:.1f}%)",
        f"Unsupported: {summary['n_unsupported']} ({summary['n_unsupported'] / n * 100:.1f}%)",
        "",
        f"High-risk unsupported rate: {summary['high_risk_unsupported_rate'] * 100:.1f}%",
        "",
        "## Unsupported claims (review before submission)",
        "",
    ]
    unsupported = [c for c in claims if by_id.get(c["id"], {}).get("support") == "UNSUPPORTED"]
    if not unsupported:
        lines.append("(none)")
    else:
        for c in unsupported:
            ent = by_id.get(c["id"], {})
            lines.append(f"- [{c['section']}] {c['claim']}")
            best = ent.get("retrieved") or []
            if best:
                ev = best[0]
                lines.append(f"  - Best retrieved evidence: {ev.get('source', '?')} pages {ev.get('pages', '?')}")
            else:
                lines.append("  - Best retrieved evidence: (none)")
            lines.append(f"  - Why it failed: {ent.get('rationale', '(no rationale)')}")
    lines.append("")

    # Partial section (smaller but worth showing)
    partial = [c for c in claims if by_id.get(c["id"], {}).get("support") == "PARTIALLY_SUPPORTED"]
    if partial:
        lines.append("## Partially supported claims")
        lines.append("")
        for c in partial:
            ent = by_id.get(c["id"], {})
            lines.append(f"- [{c['section']}] {c['claim']}")
            lines.append(f"  - Note: {ent.get('rationale', '(no rationale)')}")
        lines.append("")

    # High-risk breakdown table — group by section, count by support label
    section_stats: dict[str, dict[str, int]] = {}
    for c in claims:
        sec = c["section"]
        ent = by_id.get(c["id"], {})
        sup = ent.get("support", "ERROR")
        bucket = section_stats.setdefault(sec, {"total": 0, "SUPPORTED": 0, "PARTIALLY_SUPPORTED": 0, "UNSUPPORTED": 0, "ERROR": 0})
        bucket["total"] += 1
        bucket[sup if sup in bucket else "ERROR"] += 1

    high_risk_sections = [(s, st) for s, st in section_stats.items() if _is_high_risk(s)]
    lines.append("## High-risk section breakdown")
    lines.append("")
    if not high_risk_sections:
        lines.append("(no sections matched the high-risk keyword filter)")
    else:
        lines.append("| Section | Total | Supported | Partial | Unsupported |")
        lines.append("|---|---|---|---|---|")
        for sec, st in sorted(high_risk_sections):
            lines.append(
                f"| {sec} | {st['total']} | {st['SUPPORTED']} | "
                f"{st['PARTIALLY_SUPPORTED']} | {st['UNSUPPORTED']} |"
            )
    lines.append("")

    # All-section breakdown for completeness
    lines.append("## All sections")
    lines.append("")
    lines.append("| Section | Total | Supported | Partial | Unsupported |")
    lines.append("|---|---|---|---|---|")
    for sec, st in sorted(section_stats.items()):
        marker = " (high-risk)" if _is_high_risk(sec) else ""
        lines.append(
            f"| {sec}{marker} | {st['total']} | {st['SUPPORTED']} | "
            f"{st['PARTIALLY_SUPPORTED']} | {st['UNSUPPORTED']} |"
        )
    lines.append("")

    return "\n".join(lines)


def run_groundedness_check(
    business_plan_md: str,
    output_dir: Path | str,
    project: str = "capstone",
    extract_model: str = CLAUDE_MODEL_FAST,
    entail_model: str = CLAUDE_MODEL_FAST,
) -> dict:
    """Full pipeline: extract claims → entail each → write report.

    Parameters
    ----------
    business_plan_md
        The raw markdown of the business plan.
    output_dir
        Directory to write claims.json, entailment.json, groundedness_report.md.
        Created if it doesn't exist.
    project
        ChromaDB project filter for evidence retrieval. Defaults to ``"capstone"``.
    extract_model, entail_model
        Claude model names for the two LLM stages. Sonnet by default for cost;
        bump to ``"opus"`` for higher-stakes runs.

    Returns
    -------
    dict
        {
          "n_claims": int,
          "n_supported": int,
          "n_partial": int,
          "n_unsupported": int,
          "n_error": int,
          "unsupported_rate": float,
          "high_risk_unsupported_rate": float,
        }
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Groundedness step 1: extracting claims from %d-char plan...", len(business_plan_md))
    claims = extract_claims(business_plan_md, model=extract_model)

    if not claims:
        logger.warning("Groundedness: no claims extracted — writing empty report")
        empty_summary = {
            "n_claims": 0, "n_supported": 0, "n_partial": 0,
            "n_unsupported": 0, "n_error": 0,
            "unsupported_rate": 0.0, "high_risk_unsupported_rate": 0.0,
        }
        (out_dir / "claims.json").write_text(
            json.dumps([], indent=2, ensure_ascii=False), encoding="utf-8",
        )
        (out_dir / "entailment.json").write_text(
            json.dumps([], indent=2, ensure_ascii=False), encoding="utf-8",
        )
        (out_dir / "groundedness_report.md").write_text(
            _render_markdown_report("(business_plan.md)", [], [], empty_summary),
            encoding="utf-8",
        )
        return empty_summary

    (out_dir / "claims.json").write_text(
        json.dumps(claims, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    logger.info("Groundedness step 2: entailing %d claims (model=%s)...", len(claims), entail_model)
    entailments: list[dict] = []
    for i, c in enumerate(claims, start=1):
        logger.info("  [%d/%d] %s — %s", i, len(claims), c["id"], c["claim"][:80])
        e = entail_claim(c, retrieved_chunks=None, model=entail_model, project=project)
        entailments.append(e)

    (out_dir / "entailment.json").write_text(
        json.dumps(entailments, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # Summary statistics
    n = len(claims)
    by_id = {e["claim_id"]: e for e in entailments}
    n_sup = sum(1 for c in claims if by_id.get(c["id"], {}).get("support") == "SUPPORTED")
    n_part = sum(1 for c in claims if by_id.get(c["id"], {}).get("support") == "PARTIALLY_SUPPORTED")
    n_unsup = sum(1 for c in claims if by_id.get(c["id"], {}).get("support") == "UNSUPPORTED")
    n_err = sum(1 for c in claims if by_id.get(c["id"], {}).get("support") == "ERROR")

    high_risk_claims = [c for c in claims if _is_high_risk(c["section"], c["claim"])]
    n_hr = len(high_risk_claims)
    n_hr_unsup = sum(
        1 for c in high_risk_claims
        if by_id.get(c["id"], {}).get("support") == "UNSUPPORTED"
    )
    # ERROR = the entailment call failed → the claim is UNVERIFIED, not verified.
    # It counts toward the blocking rate (finding F05): otherwise an all-ERROR run
    # (e.g. the CLI hits its plan limit right after the expensive plan generation)
    # reports 0 unsupported and PASSES a completely unverified plan.
    n_hr_err = sum(
        1 for c in high_risk_claims
        if by_id.get(c["id"], {}).get("support") == "ERROR"
    )
    n_hr_blocking = n_hr_unsup + n_hr_err

    summary = {
        "n_claims": n,
        "n_supported": n_sup,
        "n_partial": n_part,
        "n_unsupported": n_unsup,
        "n_error": n_err,
        "unsupported_rate": (n_unsup / n) if n else 0.0,
        # UNSUPPORTED-only rate, kept for reporting continuity.
        "high_risk_unsupported_rate": (n_hr_unsup / n_hr) if n_hr else 0.0,
        # The metric the export gate blocks on: unsupported OR unverifiable(ERROR).
        "high_risk_blocking_rate": (n_hr_blocking / n_hr) if n_hr else 0.0,
        "n_high_risk_claims": n_hr,
        "n_high_risk_unsupported": n_hr_unsup,
        "n_high_risk_error": n_hr_err,
        "n_high_risk_blocking": n_hr_blocking,
    }

    report_md = _render_markdown_report("business_plan.md", claims, entailments, summary)
    (out_dir / "groundedness_report.md").write_text(report_md, encoding="utf-8")

    logger.info(
        "Groundedness done: %d claims, supported=%d, partial=%d, unsupported=%d, error=%d (high-risk unsupported %d/%d)",
        n, n_sup, n_part, n_unsup, n_err, n_hr_unsup, n_hr,
    )
    return summary
