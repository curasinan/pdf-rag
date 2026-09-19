"""Bisect which part of the arm C invocation breaks CLI authentication.

Run this from the SAME plain terminal where tools/probe_agentic.py failed.

Background
==========
``probe_agentic.py`` reported ``Invalid API key · Fix external API key``. That
message means a credential was **found and rejected** (HTTP 401) — distinct from
``Not logged in · Please run /login``, which means none was found at all. So
either the shell supplies a stale credential the CLI prefers over the
subscription login, or one of the sandbox flags changes credential resolution.

Documented auth precedence (Claude Code): cloud-provider vars →
``ANTHROPIC_AUTH_TOKEN`` → ``ANTHROPIC_API_KEY`` → ``apiKeyHelper`` →
``CLAUDE_CODE_OAUTH_TOKEN`` → subscription OAuth. In ``-p`` mode an
``ANTHROPIC_API_KEY`` present in the environment is always used, even when a
valid subscription login exists.

Each variant below is one cheap Haiku call with a three-token prompt.

Usage
=====
    python tools/diagnose_agentic_auth.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from tools.build_mirror import default_mirror_dir      # noqa: E402

PROMPT = "Reply with exactly: OK"
MODEL = "haiku"

AUTH_VARS = (
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN",
    "ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL", "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY", "CLAUDECODE",
    "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_ENTRYPOINT",
)


def show_env() -> None:
    print("=" * 72)
    print("ENVIRONMENT (values masked)")
    print("=" * 72)
    any_set = False
    for k in AUTH_VARS:
        v = os.environ.get(k)
        if v is None:
            continue
        any_set = True
        shown = v if len(v) <= 12 else f"{v[:6]}…{v[-4:]} ({len(v)} chars)"
        print(f"  {k} = {shown}")
    if not any_set:
        print("  (none set)")
    if os.environ.get("CLAUDECODE") or os.environ.get("CLAUDE_CODE_CHILD_SESSION"):
        print("\n  WARNING: this looks like a shell INSIDE a Claude Code session.")
        print("  A `claude` subprocess started here cannot inherit host auth refresh.")
        print("  Re-run from a plain terminal (Windows Terminal / PowerShell / Git Bash).")
    print()


def run_variant(label: str, extra: list[str], env_overrides: dict | None = None,
                mirror: Path | None = None) -> bool:
    cmd = ["claude", "-p", "--model", MODEL] + extra
    env = dict(os.environ)
    for k, v in (env_overrides or {}).items():
        if v is None:
            env.pop(k, None)
        else:
            env[k] = v
    try:
        r = subprocess.run(
            cmd, input=PROMPT, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=180,
            cwd=str(mirror) if mirror else None, env=env,
        )
    except subprocess.TimeoutExpired:
        print(f"  {label:<44} TIMEOUT")
        return False
    except FileNotFoundError:
        print(f"  {label:<44} claude not on PATH")
        return False

    ok = r.returncode == 0
    msg = ((r.stdout or "").strip() or (r.stderr or "").strip() or "(no output)")
    first = msg.splitlines()[0][:60] if msg else ""
    print(f"  {label:<44} {'PASS' if ok else 'FAIL'}  {first}")
    return ok


def main() -> int:
    show_env()
    mirror = default_mirror_dir()
    if not (mirror / "_manifest.json").exists():
        print(f"No mirror at {mirror}; run python tools/build_mirror.py first.")
        return 1

    print("=" * 72)
    print("BISECTION  (each row is one cheap haiku call)")
    print("=" * 72)

    results = {}

    # 0. Does auth work at all in this shell?
    results["baseline"] = run_variant("0. plain `claude -p` (no extra flags)", [])

    # 1. With ANTHROPIC_API_KEY explicitly removed from the child env.
    if os.environ.get("ANTHROPIC_API_KEY"):
        results["no_key"] = run_variant(
            "1. plain, ANTHROPIC_API_KEY unset for child", [],
            env_overrides={"ANTHROPIC_API_KEY": None},
        )
    else:
        print("  1. (skipped: ANTHROPIC_API_KEY is not set)")

    # 2. The exact failing invocation.
    full = [
        "--output-format", "json",
        "--tools", "Read,Grep,Glob",
        "--disallowedTools", "Bash Write Edit NotebookEdit WebFetch WebSearch Task",
        "--add-dir", str(mirror),
        "--permission-mode", "default",
        "--setting-sources", "",
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--no-session-persistence",
    ]
    results["full"] = run_variant("2. full arm-C flag set (current code)", full, mirror=mirror)

    # 3. Same, minus the suspect flag.
    without_ss = [a for i, a in enumerate(full)
                  if a != "--setting-sources" and not (i and full[i - 1] == "--setting-sources")]
    results["no_setting_sources"] = run_variant(
        "3. full set MINUS --setting-sources", without_ss, mirror=mirror)

    # 4. Same, with valid (documented) --setting-sources syntax.
    valid_ss = without_ss + ["--setting-sources", "project,local"]
    results["valid_setting_sources"] = run_variant(
        "4. full set WITH --setting-sources project,local", valid_ss, mirror=mirror)

    # 5. Isolate the flag on its own.
    results["ss_alone"] = run_variant(
        '5. ONLY --setting-sources "" (nothing else)', ["--setting-sources", ""])

    print()
    print("=" * 72)
    print("DIAGNOSIS")
    print("=" * 72)
    if not results.get("baseline"):
        if results.get("no_key"):
            print("  ANTHROPIC_API_KEY in this shell is stale/invalid and takes precedence")
            print("  over your subscription login in -p mode.")
            print("  Fix: unset it for this shell, or let the bridge strip it (see below).")
        else:
            print("  Auth is broken for ALL invocations, including a bare `claude -p`.")
            print("  This is not a flag problem. Run `claude` interactively and /login,")
            print("  and confirm you are in a plain terminal (see the warning above).")
    elif results.get("full"):
        print("  The full flag set works now — the earlier failure was transient.")
    elif results.get("no_setting_sources") or results.get("valid_setting_sources"):
        print("  CONFIRMED: `--setting-sources \"\"` is the culprit.")
        print("  An empty value is not documented syntax (valid values are")
        print("  user / project / local, comma-separated).")
        if results.get("valid_setting_sources"):
            print("  Fix: use --setting-sources project,local (skips USER settings,")
            print("  hence user hooks; project/local resolve to nothing from the mirror).")
        else:
            print("  Fix: drop --setting-sources; rely on cwd isolation + the hook")
            print("  env kill switches, and verify with probe 3 (project memory).")
    else:
        print("  Some other flag in the set is responsible; results above show which")
        print("  variants passed. Re-run with flags removed one at a time.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
