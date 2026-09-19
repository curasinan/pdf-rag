"""Add `citation_claim_support` to existing results files without regenerating answers.

This is what makes the metric cheap: claim support is computable from the stored
``actual_answer`` plus the corpus, so no generation is re-run and
``eval/baseline.json`` does not need regenerating.

Guard worth understanding before using ``--force``: stored ``retrieved`` records
carry only (source, pages), so chunk TEXT has to be re-resolved from the live
vectorstore. A backfill run against a re-ingested corpus would therefore score
against different chunk boundaries and produce plausible-looking numbers that are
not comparable to anything. ``corpus_signature`` makes that detectable.

Usage:
    python eval/backfill_citation_support.py eval/results_hard.json [more.json ...]
                                             [--runs 1] [--cache-dir PATH] [--force]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from citation_support import (build_idf, llm_adjudicator,          # noqa: E402
                              score_citation_support)
from config import (CITATION_SUPPORT_CACHE_DIR,                    # noqa: E402
                    CITATION_SUPPORT_PROMPT_VERSION, CITATION_SUPPORT_RUNS)
from vectorstore import get_all_chunks                             # noqa: E402

EVAL_PROJECT = "capstone"


def _flush(path: Path, env: dict, runs: int, scope: str, sig: str) -> None:
    """Atomic write of the envelope, so a kill mid-write cannot corrupt the file."""
    env["citation_support_runs"] = runs
    env["citation_support_scope"] = scope
    env["citation_support_prompt_version"] = CITATION_SUPPORT_PROMPT_VERSION
    env["citation_support_corpus_signature"] = sig
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(env, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def corpus_signature(chunks: list[dict]) -> str:
    ids = sorted(str(c.get("id") or "") for c in chunks)
    return f"{len(chunks)}:{ids[-1][-24:] if ids else ''}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--runs", type=int, default=CITATION_SUPPORT_RUNS)
    ap.add_argument("--cache-dir", default=CITATION_SUPPORT_CACHE_DIR)
    ap.add_argument("--force", action="store_true",
                    help="Write even if the corpus signature differs from a recorded one.")
    ap.add_argument("--only", default=None, help="Comma-separated question ids.")
    args = ap.parse_args()

    chunks = get_all_chunks(project=EVAL_PROJECT)
    idf = build_idf(chunks)
    sig = corpus_signature(chunks)
    adj = llm_adjudicator()
    wanted = {s.strip() for s in args.only.split(",")} if args.only else None

    for fname in args.files:
        path = Path(fname)
        if not path.exists():
            print(f"skip {fname}: not found")
            continue
        env = json.loads(path.read_text(encoding="utf-8"))
        recorded = env.get("citation_support_corpus_signature")
        if recorded and recorded != sig and not args.force:
            print(f"REFUSE {fname}: corpus signature changed ({recorded} -> {sig}). "
                  f"Chunk boundaries moved; rescoring would not be comparable. Use --force.")
            continue

        arm = (env.get("arm") or "A").upper()
        scope = "corpus_only" if arm == "C" else "own"
        done = skipped = 0
        for r in env.get("results", []):
            if wanted and r.get("id") not in wanted:
                continue
            answer = r.get("actual_answer") or ""
            if not answer:
                continue
            existing = r.get("citation_claim_support")
            if (existing and existing.get("prompt_version") == CITATION_SUPPORT_PROMPT_VERSION
                    and existing.get("support_runs") == args.runs):
                skipped += 1
                continue
            if arm == "C":
                universe = chunks
            else:
                # Reconstruct the arm's own retrieved set from the stored projection.
                keys = {(c.get("source"), str(c.get("pages"))) for c in (r.get("retrieved") or [])}
                universe = [c for c in chunks
                            if (c.get("source"), str(c.get("pages"))) in keys] or chunks
            r["citation_claim_support"] = score_citation_support(
                answer, universe, scope=scope, runs=args.runs,
                adjudicator=adj, idf=idf, cache_dir=args.cache_dir)
            done += 1
            print(f"  {r.get('id')}: {r['citation_claim_support']['claim_support_avg']}",
                  flush=True)
            # Write after EVERY question. The first version wrote once at the end,
            # and a single hung CLI call threw away a whole arm's scoring — the same
            # failure the eval harness already learned to checkpoint against.
            # Re-running is then cheap twice over: completed questions are skipped by
            # the prompt_version check, and completed adjudicator calls replay from
            # the support cache.
            _flush(path, env, args.runs, scope, sig)

        _flush(path, env, args.runs, scope, sig)
        print(f"{fname}: scored {done}, skipped {skipped} (already current)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
