"""Post-hoc leakage scan (plan Phase 2 verification, never run).

questions_hard.json holds every gold answer. If arm C's sandbox leaked, its
answers would contain verbatim spans from expected_answer that arms A and B —
which never see the file — could not produce. Arms A and B are the control:
whatever n-gram overlap they show is the floor produced by both describing the
same source text.

Pure string matching, no LLM calls.
"""
import io
import json
import re
from pathlib import Path

EVAL = Path("eval")
N = 8

FILES = {
    "A": "results_hard_corpus.json",
    "B": "results_hard_B_corpus.json",
    "C": "results_hard_C_corpus.json",
}


def norm(t: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", (t or "").lower())


def grams(toks, n=N):
    return {tuple(toks[i:i + n]) for i in range(len(toks) - n + 1)}


rows = {}
for arm, f in FILES.items():
    d = json.loads(io.open(EVAL / f, encoding="utf-8").read())
    for r in d["results"]:
        rows.setdefault(r["id"], {})[arm] = r

totals = {a: 0 for a in FILES}
worst = []
for qid in sorted(rows):
    exp = rows[qid]["A"]["expected_answer"]
    eg = grams(norm(exp))
    if not eg:
        continue
    hit = {}
    for a in FILES:
        ag = grams(norm(rows[qid][a].get("actual_answer", "")))
        shared = eg & ag
        hit[a] = len(shared)
        totals[a] += len(shared)
    if any(hit.values()):
        worst.append((qid, hit))

print(f"Verbatim {N}-gram overlap with expected_answer (arms A/B are the control)\n")
print(f"{'qid':<6} {'A':>4} {'B':>4} {'C':>4}")
for qid, h in worst:
    print(f"{qid:<6} {h['A']:>4} {h['B']:>4} {h['C']:>4}")
if not worst:
    print("(no question showed any overlap for any arm)")
print(f"\nTOTAL  {totals['A']:>4} {totals['B']:>4} {totals['C']:>4}")

excess = totals["C"] - max(totals["A"], totals["B"])
print(f"\nArm C excess over the higher control: {excess}")
print("VERDICT:", "NO LEAK SIGNAL" if excess <= 0 else "INVESTIGATE — arm C exceeds controls")
