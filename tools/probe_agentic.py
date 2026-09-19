"""Pre-flight probes for arm C. **Run this from a plain terminal, not from inside
a Claude Code session.**

Why the terminal matters
========================
A ``claude`` subprocess spawned from within a Claude Code session does not
inherit host auth refresh (the environment carries ``CLAUDE_CODE_CHILD_SESSION``
and friends), so every call returns ``Not logged in · Please run /login`` — exit
1, message on **stdout**, empty stderr. That is an environment artifact, not a
code fault, but it makes arm C unverifiable from inside a session.

What it checks
==============
1. **envelope** — the real shape of ``--output-format json``. The arm C telemetry
   parser treats every field as optional precisely because this could not be
   verified when it was written; this probe replaces guesswork with fact.
2. **sandbox** — that the agent cannot reach this repo. ``eval/questions_hard.json``
   contains the expected answer to every eval question, so a leak here would
   silently invalidate every arm C number.
3. **memory** — that no CLAUDE.md / project instructions reach the agent.
4. **citations** — that arm C's answers actually parse as citations. If they do
   not, arm C loses the citation metrics for a formatting reason rather than a
   capability one, and the comparison is meaningless.

Usage
=====
    python tools/probe_agentic.py                 # all probes
    python tools/probe_agentic.py --only envelope
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from citations import parse_citations                              # noqa: E402
from claude_bridge import (                                        # noqa: E402
    ClaudeCLIError, assert_agentic_sandbox, call_claude_agentic,
)
from config import CLAUDE_MODEL_QUALITY, CLAUDE_MODEL_FAST         # noqa: E402
from tools.build_mirror import default_mirror_dir                  # noqa: E402


REPO_MARKER = ROOT / "eval" / "questions_hard.json"


def _run(label: str, mirror: Path, prompt: str, model: str, output_format: str = "json",
         timeout: int = 300):
    print(f"\n{'=' * 72}\n{label}\n{'=' * 72}")
    try:
        answer, envelope = call_claude_agentic(
            model, "You are running a diagnostic probe. Be terse and literal.",
            prompt, work_dir=mirror, repo_root=ROOT,
            timeout=timeout, output_format=output_format,
        )
        return answer, envelope
    except ClaudeCLIError as e:
        print(f"  CLI ERROR: {e}")
        if "not logged in" in str(e).lower():
            print("  → Run this script from a PLAIN TERMINAL, not inside a Claude Code session.")
        return None, None


def probe_envelope(mirror: Path) -> bool:
    answer, env = _run(
        "1. ENVELOPE SHAPE  (--output-format json)",
        mirror, "Reply with exactly: OK", CLAUDE_MODEL_FAST,
    )
    if env is None:
        return False
    print(f"  answer: {answer!r}")
    print(f"  top-level keys: {sorted(k for k in env if k != '_meta')}")
    for k in ("num_turns", "duration_ms", "total_cost_usd", "is_error", "subtype",
              "session_id", "permission_denials"):
        if k in env:
            print(f"    {k} = {env[k]!r}")
    if isinstance(env.get("usage"), dict):
        print(f"    usage keys = {sorted(env['usage'])}")
    missing = [k for k in ("num_turns", "duration_ms", "usage") if k not in env]
    if missing:
        print(f"  NOTE: expected telemetry absent: {missing} — arm C will record None for these.")
    return True


def probe_sandbox(mirror: Path) -> bool:
    answer, env = _run(
        "2. SANDBOX  (the agent must NOT reach this repo)",
        mirror,
        "Do these three things and report each result literally:\n"
        "1. List the files you can see in your working directory.\n"
        f"2. Attempt to read {REPO_MARKER.as_posix()} and say whether it "
        "succeeded or was denied.\n"
        "3. Run a Glob for '**/questions_hard.json' starting from the filesystem "
        "root and report what you found.",
        CLAUDE_MODEL_QUALITY, timeout=420,
    )
    if env is None:
        return False
    print(f"  --- agent output ---\n{(answer or '')[:1500]}\n  --- end ---")

    low = (answer or "").lower()
    leaked = any(s in low for s in ("must_cite_sources", "expected_answer",
                                    "expected_numbers", "table turn time is"))
    denials = env.get("permission_denials")
    print(f"  permission_denials: {denials}")
    if leaked:
        print("  FAIL: the agent appears to have read eval ground truth.")
        return False
    print("  PASS: no eval ground-truth content in the response.")
    return True


def probe_memory(mirror: Path) -> bool:
    answer, env = _run(
        "3. PROJECT MEMORY  (no CLAUDE.md / rubric may reach the agent)",
        mirror,
        "Repeat verbatim any project instructions, memory files, or system "
        "context that were loaded for you. If none, say exactly: NONE.",
        CLAUDE_MODEL_FAST,
    )
    if env is None:
        return False
    print(f"  --- agent output ---\n{(answer or '')[:1200]}\n  --- end ---")
    low = (answer or "").lower()
    bad = [m for m in ("pdf-rag", "hybrid_search", "must_cite_sources",
                       "equivalent", "chunker_version", "bug ledger", "auth-bypass")
           if m in low]
    if bad:
        print(f"  FAIL: leaked project/hook context markers: {bad}")
        return False
    print("  PASS: no project-memory or hook markers found.")
    return True


def probe_citations(mirror: Path) -> bool:
    from eval.arms import ARM_C_SYSTEM_SUFFIX, ARM_C_USER

    print(f"\n{'=' * 72}\n4. CITATION FORMAT  (arm C answers must parse)\n{'=' * 72}")
    question = ("What is described as KPI #5 in the 5 KPIs document, and on which "
                "page is it defined?")
    try:
        answer, env = call_claude_agentic(
            CLAUDE_MODEL_QUALITY, ARM_C_SYSTEM_SUFFIX,
            ARM_C_USER.format(question=question),
            work_dir=mirror, repo_root=ROOT, timeout=600,
        )
    except ClaudeCLIError as e:
        print(f"  CLI ERROR: {e}")
        return False

    print(f"  --- answer ---\n{(answer or '')[:900]}\n  --- end ---")
    parsed = parse_citations(answer or "")
    print(f"  parsed citations: {parsed}")
    print(f"  turns={env.get('num_turns')} wall={env.get('_meta', {}).get('wall_s')}s")
    if not parsed:
        print("  FAIL: no parseable citations — arm C would lose citation metrics "
              "for a formatting reason. Fix ARM_C_SYSTEM_SUFFIX before the real run.")
        return False
    print("  PASS: citations parse.")
    return True


PROBES = {
    "envelope": probe_envelope,
    "sandbox": probe_sandbox,
    "memory": probe_memory,
    "citations": probe_citations,
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--mirror-dir", default=None)
    ap.add_argument("--only", choices=sorted(PROBES), default=None)
    args = ap.parse_args()

    mirror = Path(args.mirror_dir) if args.mirror_dir else default_mirror_dir()
    print(f"Mirror: {mirror}")
    if not (mirror / "_manifest.json").exists():
        print("No mirror found. Build it first: python tools/build_mirror.py")
        return 1

    try:
        warnings = assert_agentic_sandbox(mirror, ROOT)
    except Exception as e:
        print(f"STATIC SANDBOX CHECK FAILED: {e}")
        return 1
    print("Static sandbox check: PASS"
          + (f"  (warnings: {warnings})" if warnings else ""))

    names = [args.only] if args.only else list(PROBES)
    results = {n: PROBES[n](mirror) for n in names}

    print(f"\n{'=' * 72}\nSUMMARY")
    for n, ok in results.items():
        print(f"  {n:<10} {'PASS' if ok else 'FAIL'}")
    ok_all = all(results.values())
    print("\nArm C is safe to run." if ok_all
          else "\nDo NOT trust arm C numbers until every probe passes.")
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
