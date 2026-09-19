"""Single point where the system shells out to the Claude Code CLI.

Why a separate module: both `pipeline.py` (answers, summaries, judges) and
`hyde.py` (hypothetical-answer generation for retrieval) need to call Claude.
Putting `_call_claude` in `pipeline.py` and importing it from `hyde.py` would
create a circular reference (pipeline → retrieval → hyde → pipeline). This
module breaks the cycle without otherwise changing behavior.

The contract is identical to the previous `pipeline._call_claude`: stdin-piped
prompt, stdout returned as text. Plan limits, no API charges.

Determinism (Weekend-3 B4)
==========================
We accept a ``temperature`` parameter that judges and entailment callers set
to 0.0. Verified by running ``claude -p --help`` (Weekend-3 prep): the Claude
Code CLI today does NOT expose ``--temperature`` or ``--seed`` flags — the
only sampling-relevant knobs are ``--model``, ``--effort``, and
``--fallback-model``. We still take ``temperature`` here because:

1. It documents caller intent (judges want determinism, generation wants
   variability) at the call site.
2. When this bridge is ported to the Anthropic SDK or a future CLI release
   that exposes the flag, only this file changes — every caller is already
   passing the right value.
3. Logging the requested temperature alongside the call lets us spot the gap
   (same judge prompt, different verdict) in production traces, instead of
   it manifesting as silent flakiness.

Today the gap is real: re-running ``_judge_once`` on identical input can yield
different scores. The B6 calibration harness measures the resulting flip-rate
empirically; B4 here is the contract change that lets us close the gap once
the platform supports it.
"""

import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# Sentinel for "no temperature override requested". Distinguishes
# ``temperature=0.0`` (deterministic intent) from "use the model default".
_DEFAULT_TEMPERATURE = "default"

# Neutral working directory for the CLI subprocess (finding F24). The Claude Code
# CLI auto-loads project memory (CLAUDE.md) from its cwd and ancestors in ``-p``
# mode. Inheriting the repo cwd leaked this project's CLAUDE.md — which documents
# the eval rubric and expected-results tables — into every generation, HyDE,
# judge, and entailment call, so judges were not evidence-only. Running from a
# neutral temp dir keeps each call hermetic.
_NEUTRAL_CWD = tempfile.gettempdir()


# ── SDK backend (opt-in; the CLI stays the default) ──────────────────

_SDK_CLIENT = None


def _sdk_client():
    """Singleton Anthropic client. Imported lazily so the CLI path never needs it."""
    global _SDK_CLIENT
    if _SDK_CLIENT is None:
        try:
            import anthropic
        except ImportError as e:                                   # pragma: no cover
            raise ClaudeCLIError(
                "PDFRAG_BRIDGE=sdk but the `anthropic` package is not installed "
                "(pip install anthropic)."
            ) from e
        from config import SDK_MAX_RETRIES
        _SDK_CLIENT = anthropic.Anthropic(max_retries=SDK_MAX_RETRIES)
    return _SDK_CLIENT


def _assert_sdk_opt_in() -> None:
    """The SDK path is metered API billing. Require BOTH switches, explicitly.

    `_plan_auth_env()` strips ANTHROPIC_API_KEY because that is correct for the
    CLI — the key would override subscription OAuth and silently meter every
    call. The SDK *requires* that key. Those two facts invert, so the guard has
    to be per-backend and the SDK has to be double-opt-in: flipping one env var
    must never be able to start a bill.
    """
    from config import BRIDGE_BACKEND
    if BRIDGE_BACKEND != "sdk":
        return
    if os.environ.get("PDFRAG_ALLOW_API_KEY") != "1":
        raise ClaudeCLIError(
            "PDFRAG_BRIDGE=sdk requires PDFRAG_ALLOW_API_KEY=1. The SDK path is "
            "METERED API BILLING, not plan limits — set both switches knowingly."
        )
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise ClaudeCLIError(
            "PDFRAG_BRIDGE=sdk requires ANTHROPIC_API_KEY to be set."
        )


def _sdk_model(model: str) -> str:
    """CLI aliases are not valid API model IDs; map or pass through a full ID."""
    from config import MODEL_IDS
    return MODEL_IDS.get(model, model)


def _map_sdk_error(e: Exception) -> Exception:
    """Preserve every caller's existing `except` clauses across backends."""
    import anthropic
    if isinstance(e, (anthropic.AuthenticationError, anthropic.RateLimitError)):
        # Same class as a CLI quota/auth stop: abort the run, don't score it.
        return SessionLimitError(f"SDK auth/rate limit: {e}")
    if isinstance(e, (anthropic.APIError, anthropic.APIConnectionError)):
        return ClaudeCLIError(f"SDK error: {e}")
    return ClaudeCLIError(f"SDK error: {e}")


def _call_sdk(model: str, system: str, user: str, timeout: int,
              temperature: float | str) -> dict:
    """One SDK call. Returns a CLI-shaped envelope so callers need no changes.

    `temperature` is accepted and DROPPED. Sampling parameters were removed from
    the Opus 4.7 generation onward: `claude-opus-5` and `claude-sonnet-5` reject
    `temperature` with a 400. The project convention of passing `temperature=0.0`
    on verifier calls therefore records intent only — forwarding it would make
    every judge and entailment call fail. This is the one place the SDK port
    cannot deliver what the CLI-era docstring promised.
    """
    _assert_sdk_opt_in()
    from config import SDK_MAX_TOKENS
    client = _sdk_client()
    kwargs = {
        "model": _sdk_model(model),
        "max_tokens": SDK_MAX_TOKENS,
        "messages": [{"role": "user", "content": user}],
    }
    if system:
        kwargs["system"] = system          # a real system role, not concatenated stdin
    try:
        msg = client.with_options(timeout=float(timeout)).messages.create(**kwargs)
    except Exception as e:                                          # noqa: BLE001
        raise _map_sdk_error(e) from e

    if getattr(msg, "stop_reason", None) == "refusal":
        raise ClaudeCLIError(
            f"SDK refusal (category="
            f"{getattr(getattr(msg, 'stop_details', None), 'category', None)})"
        )
    text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
    u = getattr(msg, "usage", None)
    return {
        "result": text.strip(),
        # Synthesized so `total_input_tokens` and eval/ablation_report.py work
        # unchanged across backends.
        "usage": {
            "input_tokens": getattr(u, "input_tokens", 0) or 0,
            "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", 0) or 0,
            "cache_creation_input_tokens": getattr(u, "cache_creation_input_tokens", 0) or 0,
            "output_tokens": getattr(u, "output_tokens", 0) or 0,
        },
    }


def count_input_tokens(system: str, user: str, model: str) -> int:
    """Token count for (system, user). SDK: real counter. CLI: chars // 4."""
    from config import BRIDGE_BACKEND
    if BRIDGE_BACKEND == "sdk":
        _assert_sdk_opt_in()
        try:
            kw = {"model": _sdk_model(model),
                  "messages": [{"role": "user", "content": user}]}
            if system:
                kw["system"] = system
            return _sdk_client().messages.count_tokens(**kw).input_tokens
        except Exception as e:                                      # noqa: BLE001
            raise _map_sdk_error(e) from e
    return (len(system or "") + len(user or "")) // 4


#: Credential env vars the CLI prefers over subscription login. In ``-p`` mode an
#: ``ANTHROPIC_API_KEY`` present in the environment is *always* used, even when a
#: valid subscription login exists.
_API_AUTH_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")

#: Escape hatch: set ``PDFRAG_ALLOW_API_KEY=1`` to let API-key auth through.
_ALLOW_API_KEY_VAR = "PDFRAG_ALLOW_API_KEY"


def _plan_auth_env(base: dict | None = None) -> dict:
    """Environment for a CLI subprocess, with API-key credentials removed.

    This project's stated contract (CLAUDE.md) is that generation runs on the
    Claude *subscription plan*, not the metered API. But the CLI's documented
    auth precedence puts ``ANTHROPIC_API_KEY`` / ``ANTHROPIC_AUTH_TOKEN`` ahead of
    the subscription OAuth credential, so a key sitting in the user environment
    silently redirects every call to billed API usage. On this machine there is a
    real 108-character ``sk-ant-api03-…`` key in the *user-scope* environment: a
    three-arm, 25-question ablation — arm B alone resends ~74K tokens per
    question — would have quietly become a metered bill instead of plan usage.

    Removing the variables makes the failure mode honest: with no subscription
    login you get "Not logged in · Please run /login", which is actionable,
    instead of an invoice.
    """
    env = dict(base if base is not None else os.environ)
    if env.get(_ALLOW_API_KEY_VAR) == "1":
        return env
    for var in _API_AUTH_VARS:
        if env.pop(var, None) is not None:
            logger.info(
                "%s removed from the CLI subprocess environment so the call uses "
                "plan auth, not metered API billing (set %s=1 to override).",
                var, _ALLOW_API_KEY_VAR,
            )
    return env


class ClaudeCLIError(RuntimeError):
    """Raised when the Claude Code CLI call fails (non-zero exit, timeout, or the
    ``claude`` binary is missing).

    Replaces the previous ``sys.exit(1)`` (finding F15): a typed exception lets
    interactive ``chat`` survive one flaky turn without losing history, lets
    ``summarize`` batches report partial progress, and lets the eval / HyDE /
    groundedness fallbacks catch a *specific* error instead of the blunt
    ``except SystemExit``. Top-level CLI entry points translate it to exit(1)."""


class SessionLimitError(ClaudeCLIError):
    """The CLI failed because a plan / rate / usage limit was hit, not because the
    model produced a bad answer.

    Long eval runs must distinguish the two. The default degradation path records
    a failed call as ``"[generation failed]"`` and scores it — which turns an
    infrastructure outage into a *data point*, silently biasing any comparison
    that spans the outage. Callers doing measurement should catch this, checkpoint,
    and stop rather than continue producing poisoned rows."""


# Substrings that indicate a quota / rate / auth-refresh failure rather than a
# genuine model or prompt problem. Matched case-insensitively against BOTH
# streams — see the note about stdout in ``_cli_failure_text``.
_LIMIT_MARKERS = (
    "rate limit", "usage limit", "quota", "too many requests", "429",
    "resets at", "session limit", "not logged in", "please run /login",
    "authentication", "unauthorized",
)


def _cli_failure_text(result) -> str:
    """Best available description of why the CLI failed.

    The CLI writes several fatal messages (notably ``Not logged in · Please run
    /login``) to **stdout with an empty stderr**, so a stderr-only error message
    renders as a blank reason. Prefer stderr, fall back to stdout."""
    err = (getattr(result, "stderr", "") or "").strip()
    out = (getattr(result, "stdout", "") or "").strip()
    return err or out


def _looks_like_limit(text: str) -> bool:
    """Does this CLI failure look like a quota / auth problem rather than a bad answer?"""
    low = (text or "").lower()
    return any(marker in low for marker in _LIMIT_MARKERS)


def call_claude(
    model: str,
    system: str,
    user: str,
    timeout: int = 900,
    temperature: float | str = _DEFAULT_TEMPERATURE,
) -> str:
    """Invoke ``claude -p --model <model>`` with ``{system}\\n\\n{user}`` on stdin.

    Parameters
    ----------
    model
        Claude model alias (``"sonnet"``, ``"opus"``, ``"haiku"``) or full name.
    system, user
        System and user prompt strings. Concatenated with a blank-line
        separator and piped through stdin.
    timeout
        Wall-clock seconds before the subprocess is killed. Default 900s
        (15 min) — generous so 8-12 min Opus calls don't trip it.
    temperature
        Sampling temperature. Pass ``0.0`` for judge / entailment / verifier
        calls that need deterministic output; leave at the default sentinel
        for generation calls where some variability is fine. **Note:** the
        Claude Code CLI today ignores this argument (no ``--temperature`` flag
        is exposed). The parameter is recorded in logs and forwarded to a
        future CLI release / SDK port; today it documents intent only.

    Returns
    -------
    str
        The CLI's stdout, stripped.

    Raises
    ------
    ClaudeCLIError
        On timeout, non-zero return code, or a missing ``claude`` binary. Callers
        that want to degrade gracefully (HyDE, judges, entailment, chat) catch
        this; one-shot CLI entry points let it bubble to a top-level handler that
        prints a clean message and exits non-zero.
    """
    from config import BRIDGE_BACKEND
    if BRIDGE_BACKEND == "sdk":
        return _call_sdk(model, system, user, timeout, temperature)["result"]

    prompt = f"{system}\n\n{user}"
    logger.debug(
        "claude CLI call: model=%s, prompt=%d chars, temperature=%s",
        model, len(prompt), temperature,
    )
    if isinstance(temperature, (int, float)) and temperature != 0.0:
        logger.debug(
            "  (note: CLI does not honor temperature today; recorded for trace only)"
        )
    t0 = time.time()
    try:
        result = subprocess.run(
            ["claude", "-p", "--model", model],
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",   # F40: a non-UTF-8 byte in localized CLI output must
                                # not raise UnicodeDecodeError past every handler.
            timeout=timeout,
            cwd=_NEUTRAL_CWD,   # F24: don't auto-load this repo's CLAUDE.md.
            env=_plan_auth_env(),  # plan auth, not metered API billing
        )
    except subprocess.TimeoutExpired:
        logger.error("Claude CLI call timed out after %ds.", timeout)
        raise ClaudeCLIError(f"Claude CLI timed out after {timeout}s")
    except FileNotFoundError as e:
        # F49: the `claude` binary isn't on PATH (or is an npm .cmd shim that
        # CreateProcess won't resolve). Give an actionable message, not a raw
        # traceback into subprocess internals.
        resolved = shutil.which("claude")
        hint = (
            "the resolved path failed to launch" if resolved
            else "no `claude` executable was found on PATH"
        )
        logger.error("Claude Code CLI could not be launched (%s): %s", hint, e)
        raise ClaudeCLIError(
            "Claude Code CLI not found — check `claude --version` in this shell. "
            f"({hint})"
        ) from e

    if result.returncode != 0:
        logger.error(
            "Claude CLI failed. return_code=%d stderr=%r stdout=%r prompt_len=%d",
            result.returncode,
            result.stderr[:500] if result.stderr else "(empty)",
            result.stdout[:500] if result.stdout else "(empty)",
            len(prompt),
        )
        reason = _cli_failure_text(result)
        message = f"Claude CLI exited {result.returncode}: {reason[:200]}"
        if _looks_like_limit(reason):
            # Quota / auth failure — not a model failure. Surfaced as a distinct
            # type so measurement runs can checkpoint and stop instead of scoring
            # an infrastructure outage as a wrong answer.
            raise SessionLimitError(message)
        raise ClaudeCLIError(message)
    logger.debug("claude CLI returned in %.1fs (%d chars)", time.time() - t0, len(result.stdout))
    return result.stdout.strip()


def call_claude_json(
    model: str,
    system: str,
    user: str,
    timeout: int = 900,
    temperature: float | str = _DEFAULT_TEMPERATURE,
) -> tuple[str, dict]:
    """Same contract as :func:`call_claude`, but also returns the CLI envelope.

    Exists because ``call_claude`` returns text only, so arms A and B reported no
    token counts at all while arm C (which already used ``--output-format json``)
    did. A cost comparison across arms was therefore unquotable — and cost is the
    one axis in this ablation whose confidence intervals are actually tight.

    Note ``usage.input_tokens`` alone under-reports badly: the pilot measured arm
    C at ``input_tokens=6`` with ``cache_read_input_tokens=17335``. Sum
    input + cache_read + cache_creation for a true input count — see
    :func:`total_input_tokens`.
    """
    from config import BRIDGE_BACKEND
    if BRIDGE_BACKEND == "sdk":
        env = _call_sdk(model, system, user, timeout, temperature)
        return env["result"], env

    prompt = f"{system}\n\n{user}"
    logger.debug(
        "claude CLI (json) call: model=%s, prompt=%d chars, temperature=%s",
        model, len(prompt), temperature,
    )
    t0 = time.time()
    try:
        result = subprocess.run(
            ["claude", "-p", "--model", model, "--output-format", "json"],
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=_NEUTRAL_CWD,
            env=_plan_auth_env(),
        )
    except subprocess.TimeoutExpired:
        raise ClaudeCLIError(f"Claude CLI timed out after {timeout}s")
    except FileNotFoundError as e:
        raise ClaudeCLIError(
            "Claude Code CLI not found — check `claude --version` in this shell."
        ) from e

    envelope = _parse_agentic_stdout(result.stdout, "json")
    envelope["_meta"] = {"wall_s": round(time.time() - t0, 2),
                         "returncode": result.returncode}

    # `is_error` can be true alongside subtype "success", so check it explicitly.
    if result.returncode != 0 or envelope.get("is_error"):
        reason = (str(envelope.get("result") or "").strip()
                  or _cli_failure_text(result) or "(no error text)")
        message = f"Claude CLI exited {result.returncode}: {reason[:200]}"
        if _looks_like_limit(reason):
            raise SessionLimitError(message)
        raise ClaudeCLIError(message)

    return str(envelope.get("result") or "").strip(), envelope


def total_input_tokens(usage: dict | None) -> int | None:
    """True input token count: fresh input plus both cache paths.

    ``input_tokens`` alone is near-zero when the prompt is served from cache, so
    a cost column built on it silently under-reports by orders of magnitude.
    """
    if not isinstance(usage, dict):
        return None
    parts = [usage.get("input_tokens"), usage.get("cache_read_input_tokens"),
             usage.get("cache_creation_input_tokens")]
    vals = [p for p in parts if isinstance(p, (int, float))]
    return int(sum(vals)) if vals else None


# ── Agentic (tool-enabled) invocation ────────────────────────────────
#
# Deliberately a SEPARATE function rather than a ``cwd=`` / ``tools=`` parameter
# on call_claude. call_claude has a hard contract — one shot, no tools, hermetic
# neutral cwd (F24) — and every judge and entailment call depends on it. A
# parameter that can grant file access is one typo away from un-hermeticizing
# all of them.

#: Read-only tool set for the agentic arm. ``--tools`` restricts the available
#: set (a capability restriction), which is strictly stronger than
#: ``--allowedTools`` (a permission filter): the agent cannot even attempt an
#: excluded tool. Bash is excluded specifically so the agent cannot shell out to
#: ``pdftotext`` (which IS on this machine) and grant itself an extraction
#: capability that the arm it is being compared against does not have.
AGENTIC_TOOLS = ("Read", "Grep", "Glob")

AGENTIC_DENY = (
    "Bash", "Write", "Edit", "NotebookEdit", "WebFetch", "WebSearch", "Task",
)


class AgenticSandboxError(RuntimeError):
    """The agentic sandbox could not be established, so the call was not made.

    Never downgrade this to a warning: an agent that can reach this repo can read
    ``eval/questions_hard.json``, which contains the expected answer to every
    eval question."""


def assert_agentic_sandbox(work_dir: Path, repo_root: Path) -> list[str]:
    """Fail closed unless ``work_dir`` is a safe place to run a tool-enabled agent.

    Checks, in order of severity:
      1. ``work_dir`` exists and is a directory.
      2. ``work_dir`` is NOT inside the repo — the repo holds the eval rubric
         (CLAUDE.md) and every gold answer (eval/questions_hard.json).
      3. No ``CLAUDE.md`` sits in ``work_dir`` or any ancestor, since the CLI
         auto-discovers project memory upward from cwd.

    Returns a list of non-fatal warnings (e.g. user-global memory that the CLI
    may load regardless of cwd). Raises :class:`AgenticSandboxError` on anything
    that would actually leak the corpus-under-test's answers.
    """
    work_dir = Path(work_dir).resolve()
    repo_root = Path(repo_root).resolve()

    if not work_dir.is_dir():
        raise AgenticSandboxError(f"agentic work dir does not exist: {work_dir}")

    try:
        work_dir.relative_to(repo_root)
    except ValueError:
        pass                                     # good: outside the repo
    else:
        raise AgenticSandboxError(
            f"agentic work dir {work_dir} is inside the repo {repo_root}. "
            "The CLI auto-discovers CLAUDE.md upward from cwd, and this repo "
            "contains the eval rubric and every gold answer."
        )

    for d in [work_dir, *work_dir.parents]:
        candidate = d / "CLAUDE.md"
        if candidate.exists():
            raise AgenticSandboxError(
                f"CLAUDE.md reachable from the agentic work dir at {candidate}"
            )

    warnings = []
    user_memory = Path.home() / ".claude" / "CLAUDE.md"
    if user_memory.exists():
        # Loaded independently of cwd. --setting-sources "" is passed to suppress
        # it, but that is worth surfacing rather than trusting silently.
        warnings.append(f"user-global memory exists at {user_memory}")
    return warnings


def _parse_agentic_stdout(stdout: str, output_format: str) -> dict:
    """Extract the CLI's result envelope from either output format.

    Every field is treated as optional and the raw envelope is preserved: the
    exact schema is version-dependent and could not be verified on this machine
    (a ``claude`` subprocess spawned inside a Claude Code session cannot
    authenticate). Run ``tools/probe_cli_envelope.py`` from a plain terminal to
    confirm the shape before trusting arm C telemetry.
    """
    text = (stdout or "").strip()
    if not text:
        return {}
    if output_format == "stream-json":
        envelope = {}
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict) and event.get("type") == "result":
                envelope = event          # last result event wins
        return envelope
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {"result": text, "_unparsed": True}
    return parsed if isinstance(parsed, dict) else {"result": text}


def call_claude_agentic(
    model: str,
    system_suffix: str,
    user: str,
    work_dir: Path,
    repo_root: Path,
    tools: tuple[str, ...] = AGENTIC_TOOLS,
    timeout: int = 1800,
    output_format: str = "json",
    max_budget_usd: float | None = None,
    extra_env: dict | None = None,
) -> tuple[str, dict]:
    """Run a tool-enabled Claude Code agent restricted to ``work_dir``.

    **CLI-only, unconditionally — `BRIDGE_BACKEND` does not apply.** This drives
    Claude Code's own agentic tool loop (Read/Grep/Glob inside a sandbox); the
    Messages API has no equivalent, so there is nothing to dispatch to.

    Returns ``(answer_text, envelope)``. ``envelope`` carries whatever telemetry
    the CLI reported (``num_turns``, ``duration_ms``, ``usage``,
    ``permission_denials``, ...) plus a ``_meta`` block describing the invocation.

    ``timeout`` defaults to 1800s, not call_claude's 900s: CLI 2.1.92 exposes no
    ``--max-turns``, so an agentic loop over a 242-page corpus is bounded only by
    wall clock, budget, and prompt instruction. A timeout is recorded as an ERROR,
    never as a wrong answer — otherwise arm C is biased downward by its own
    latency.
    """
    warnings = assert_agentic_sandbox(work_dir, repo_root)
    for w in warnings:
        logger.warning("agentic sandbox: %s", w)

    work_dir = Path(work_dir).resolve()
    cmd = [
        "claude", "-p",
        "--model", model,
        "--output-format", output_format,
        "--tools", ",".join(tools),
        "--disallowedTools", " ".join(AGENTIC_DENY),
        "--add-dir", str(work_dir),
        "--permission-mode", "default",   # NOT bypassPermissions: in -p mode a
                                          # prompt cannot be answered, so an
                                          # out-of-scope attempt fails visibly in
                                          # the transcript instead of succeeding.
        # Skip the USER settings source, which is where the repo owner's hooks
        # live. "project,local" is documented syntax (valid values are user /
        # project / local); an empty string is not, and undocumented syntax is
        # not something to build an experiment on. Because cwd is the mirror —
        # which has no .claude directory — project and local resolve to nothing,
        # so this is effectively "no settings at all" while staying legal.
        # Bisected 2026-07-25: this flag is NOT what broke auth (an
        # ANTHROPIC_API_KEY in the user environment was), but it is still wrong.
        "--setting-sources", "project,local",
        "--strict-mcp-config",            # no MCP servers spawn
        "--disable-slash-commands",
        "--no-session-persistence",
        "--append-system-prompt", system_suffix,
    ]
    if max_budget_usd is not None:
        cmd += ["--max-budget-usd", str(max_budget_usd)]

    env = _plan_auth_env()
    # The repo owner's ~/.claude/settings.json registers a UserPromptSubmit hook
    # that injects "bug ledger" text into every CLI prompt. These are that
    # script's own documented kill switches, set independently of
    # --setting-sources so the run is hermetic either way.
    env.update({"CRITIC_SKIP_INJECT": "1", "CRITIC_DISABLED": "1"})
    if extra_env:
        env.update(extra_env)

    t0 = time.time()
    try:
        result = subprocess.run(
            cmd, input=user, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
            cwd=str(work_dir), env=env,
        )
    except subprocess.TimeoutExpired:
        raise ClaudeCLIError(f"agentic Claude CLI timed out after {timeout}s")
    except FileNotFoundError as e:
        raise ClaudeCLIError(
            "Claude Code CLI not found — check `claude --version` in this shell."
        ) from e

    wall_s = time.time() - t0
    envelope = _parse_agentic_stdout(result.stdout, output_format)
    envelope["_meta"] = {
        "wall_s": round(wall_s, 2),
        "returncode": result.returncode,
        "cmd": cmd[:2] + ["--model", model, "--tools", ",".join(tools)],
        "work_dir": str(work_dir),
        "output_format": output_format,
        "sandbox_warnings": warnings,
    }

    # `is_error` can be true even when `subtype` says "success", so check it
    # explicitly rather than trusting the subtype or the exit code alone.
    failed = result.returncode != 0 or bool(envelope.get("is_error"))
    if failed:
        reason = (
            str(envelope.get("result") or "").strip()
            or _cli_failure_text(result)
            or "(no error text)"
        )
        message = f"agentic Claude CLI failed (rc={result.returncode}): {reason[:200]}"
        logger.error("%s", message)
        if _looks_like_limit(reason):
            raise SessionLimitError(message)
        raise ClaudeCLIError(message)

    answer = str(envelope.get("result") or "").strip()
    logger.debug(
        "agentic call finished in %.1fs, turns=%s, chars=%d",
        wall_s, envelope.get("num_turns"), len(answer),
    )
    return answer, envelope
