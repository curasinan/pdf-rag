"""Recompute `citation_validation` in place from the stored answers. No LLM calls.

Needed whenever citation parsing or source matching changes: `page_accuracy` is
GATE-TRACKED, so leaving old values in the baseline while new runs use the new
definition means the gate compares two different metrics and cannot tell — the
same failure the `judge_prompt_hash` warning was added to surface.

Prints the before/after delta per file so the change is visible rather than silent.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from citations import parse_and_validate                          # noqa: E402
from vectorstore import get_all_chunks                            # noqa: E402

EVAL_PROJECT = "capstone"


def _mean(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return sum(xs) / len(xs) if xs else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    chunks = get_all_chunks(project=EVAL_PROJECT)

    for fname in args.files:
        path = Path(fname)
        if not path.exists():
            print(f"skip {fname}: not found")
            continue
        env = json.loads(path.read_text(encoding="utf-8"))
        arm = (env.get("arm") or "A").upper()
        before, after, moved = [], [], []

        for r in env.get("results", []):
            answer = r.get("actual_answer") or ""
            if not answer:
                continue
            old = (r.get("citation_validation") or {}).get("page_accuracy")
            if arm == "C":
                universe = chunks
            else:
                keys = {(c.get("source"), str(c.get("pages")))
                        for c in (r.get("retrieved") or [])}
                universe = [c for c in chunks
                            if (c.get("source"), str(c.get("pages"))) in keys] or chunks
            fresh = parse_and_validate(answer, universe)["validation"]
            new = fresh.get("page_accuracy")
            before.append(old)
            after.append(new)
            if old != new:
                moved.append((r.get("id"), old, new))
            if not args.dry_run:
                r["citation_validation"] = fresh

        b, a = _mean(before), _mean(after)
        print(f"{path.name}: page_accuracy_avg {b:.4f} -> {a:.4f} ({a - b:+.4f}), "
              f"{len(moved)} question(s) moved")
        for qid, o, n in moved:
            print(f"    {qid}: {o} -> {n}")
        if not args.dry_run:
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(env, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
