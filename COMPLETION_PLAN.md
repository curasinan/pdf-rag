# pdf-rag — Completion Plan (Quality Freeze + SDK-Ready Bridge)

> **STATUS: COMPLETE — 2026-08-14.** Phases 2–6 executed and verified; Phase 1
> closed under its documented-gap arm (calibration NOT run — the anchors are
> `prior_verdict_mapping` remaps of the April 2026 judge's own verdicts, so a
> run measures agreement with a judge proven wrong and re-bootstrapping is
> circular; only real human labels resolve it — review F29/F30). The freeze
> landed as run **`freeze2`**, not `freeze1`: the first attempt was withheld
> after its sole gate blocker proved to be a judge false positive, and the
> judge was fixed probe-first before the sanctioned re-run (CLAUDE.md "Phase 6
> freeze TAKEN"; `HISTORY.md` "Task 20"). `eval/baseline.json` = freeze2;
> `eval/gate.py` exits 0 with zero warnings; fast suite 74/74. Grounded can
> quote the frozen numbers and adopt the bridge.

This file is the implementation spec for closing out pdf-rag before the Grounded
app work begins. Read `CLAUDE.md` first for project context. Completion means two
things and only two things: (1) quality numbers you can quote — the six-error
clearance independently verified, the judge calibrated for the first time,
baseline frozen, gate green; (2) a bridge the app can adopt — `claude_bridge`
with a config-switchable SDK backend, CLI default.

It does NOT mean: retrieval re-architecture (chunking / page-citation /
reranker rebuild goes to the app's pgvector phase), D2 adversarial suite,
D3 abstention, E2 CI, E3 failure gallery, drift/canary, a second ablation
seed, or any FastAPI/UI work. Do not build those here.

Already done — do NOT re-implement:

- The six carried-over critical errors (CITATION_WRONG h02/h06/h17,
  HALLUCINATION h03/h05/h07) were re-adjudicated in run `judgefix` and ALL
  cleared as judge-side errors. `eval/results_hard.md` reads 24/25 EQUIVALENT
  +1 PARTIAL, judge medians 5/5, flip-rate 0.020, "Critical errors: none".
  Pre-fix files live in `.backup_judgefix/`. The work below VERIFIES this
  independently; it does not redo the rubric fixes.
- `eval/calibrate.py` is written and `eval/calibration.json` has 25 anchors.
  What has never happened is a RUN of it — `eval/calibration_results.{md,json}`
  do not exist.
- `eval/gate.py`, holdout split, majority-voted critical errors, trace
  persistence, `groundedness.py`, `tools/probe_judge.py` — all built.

Marking: **[BUILD]** = Claude-executable edit/test step. **[USER]** = you
personally (plan-quota-burning eval runs from a plain terminal, judgment
calls, env vars). Long judged runs are [USER] because a `claude` subprocess
spawned inside a Claude Code session can fail auth, and because they spend
YOUR plan quota.

Cross-project dependency (the only one): **Phase 5 (SDK port) starts only
after agent-lab lessons 00–08** (`agent-lab/COMPLETION_PLAN.md` Phases 2–3) —
`agent-lab/lab/client.py` + `lab/agent.py` are the reference implementation,
and lessons 06/08 teach exactly what the port applies. Phases 1–4 and 6 have
no such dependency; if the lessons stall, run 1–4 to an interim gate-green
state rather than freezing twice.

Build in order. After each phase, run the verification command. Don't move on
if it fails.

---

## Phase 1 — Run judge calibration for the first time — **CLOSED (blocked, gap documented)**

> **Outcome (2026-08-05, unchanged since):** step 1's provenance check killed
> the run. Every anchor's label is a mechanical remap of a PRE-judgefix
> judge's own verdicts — not human labels — so running as-is measures
> agreement with a judge proven wrong on six questions, and re-bootstrapping
> from judgefix (step 1's own prescription) is circular. `calibration.json`
> left untouched; only genuine human labels resolve it. Definition-of-done
> item 1 is satisfied via its "or the gap is documented" arm.

**Why this matters.** Every claim in Phases 2–6 is measured by this judge, and
its accuracy has never been checked. `calibrate.py`'s own docstring: if
relevance/groundedness accuracy < 80% or mean flip-rate ≥ 10%, the eval gate
cannot be trusted, and no other gate should be tightened until it passes.

1. [USER] **Anchor provenance check first.** `eval/calibration.json` was
   bootstrapped (`bootstrap_method="prior_verdict_mapping"`) from a PRIOR
   results file. If that prior predates the `judgefix` rubric fix, its labels
   encode the six judge errors just cleared — the fixed judge would then
   "fail" calibration for being right. Check which run the labels came from.
   If pre-judgefix: re-bootstrap with `python eval/bootstrap_calibration.py`
   against the judgefix `eval/results_hard.json`, then hand-review the 25
   anchors (especially any involving h02/h03/h05/h06/h07/h17) and mark the
   reviewed ones.
2. [USER] From a **plain PowerShell terminal** (not inside a Claude Code
   session): `python eval/calibrate.py --runs 5`
3. [USER] Read `eval/calibration_results.md`. Acceptance: relevance accuracy
   ≥ 80%, groundedness accuracy ≥ 80%, mean flip-rate < 10%. On failure,
   decide per-item whether the judge or the anchor is wrong BEFORE touching
   any judge prompt — and after ANY rubric edit, `python tools/probe_judge.py`
   is mandatory (a change that clears disagreements looks identical to one
   that blinded the judge).
4. [BUILD] Record the calibration numbers and date in `CLAUDE.md`.

**Verification (PowerShell):**

```powershell
Test-Path eval\calibration_results.md; Test-Path eval\calibration_results.json
```

Both `True`; the MD shows per-axis accuracy + flip-rate against the targets.

---

## Phase 2 — Independently verify the six-error clearance — **DONE (2026-08-10)**

> **Outcome:** it took two passes. `verify1` tripped `WRONG_EVIDENCE` on h01
> over ONE HYPHEN (`table-turn` vs `table turn`) — an orthography artifact,
> adjudicated per step 4, fixed in `_phrase_satisfied` (193 stored
> phrase-checks replayed: one cell changes, none regress, holdout untouched).
> `verify2`: **14/15 EQUIVALENT + 1 PARTIAL (h01), medians 5/5/5, zero
> critical errors**, verdict-for-verdict identical to `judgefix`, retrieval
> byte-identical. Full working: `EVAL_NOTES.md`.

**Why this matters.** The quality bar chosen for this closeout is "fix all six
carried-over critical errors, no exceptions". They were cleared in `judgefix`
by re-judging CACHED answers. Independent verification = fresh generations,
fresh judging, tuning subset only, zero critical errors under majority vote.

1. [USER] Plain terminal: `python tools/probe_judge.py` — must still catch the
   planted fabricated-statistic and miscited answers.
2. [USER] Fresh cache dir is load-bearing — the answer cache is
   content-addressed on question/model/prompt, NOT on retrieval config or
   seed, so the default cache would replay `judgefix` answers and verify
   nothing:

   ```powershell
   python eval\run.py --hard --holdout tuning --judge-runs 3 --judge-evidence own `
     --cache-dir data\answer_cache_verify --run-id verify1 --out-suffix verify1
   ```

3. [USER] Bar: **zero critical errors under majority vote** in the `_verify1`
   results. Verdict flips on 1–2 questions vs `judgefix` are seed noise; only
   critical errors are the bar.
4. [BUILD] If any critical error resurfaces: adjudicate against the actual
   chunk text exactly as the judgefix work did. Judge-side → rubric fix +
   `tools/probe_judge.py` + re-run step 2. System-side → fix, but remember
   tuning-subset discipline: iterate here, never on holdout.

**Verification:** the `_verify1` MD report shows `Critical errors: none`, and
`python -m pytest tests/ -m "not slow"` is green.

---

## Phase 3 — F07: groundedness gate on the checked-in deliverables — **DONE (2026-08-12, FAIL recorded)**

> **Outcome:** step 3's honest-recording arm taken. 89 claims, 0 ERROR
> (verification complete), **GATE FAIL at 27.4% high-risk blocking vs 5%** —
> but 15 of the 17 blockers are the plan's own projections and operational
> choices, which no corpus can support; 2 are genuine unsourced facts. A 5%
> threshold is structurally unpassable for a projection-genre document
> (roadmap item: split the gate by claim genre). All three artifacts exist;
> the checked-in plan's sha256 verified unchanged. The regeneration hazard was
> avoided by calling `run_groundedness_check` directly, exactly as specified.

**Why this matters.** `deliverables/business_plan.md` was submitted, but
`claims.json` / `entailment.json` / `groundedness_report.md` are absent — the
capstone deliverable was never verified by the gate that exists to verify it.

**ORDERING HAZARD: do NOT run `python compose_capstone.py` for this.** Its
`main()` calls `generate_business_plan()` FIRST — a fresh Opus generation that
**overwrites the checked-in `deliverables/business_plan.md`** before the gate
runs. Call the checker directly on the existing file:

1. [USER] Plain terminal (shells out to the Claude CLI ~40–90 times):

   ```powershell
   python -c "from pathlib import Path; from groundedness import run_groundedness_check; import json; s = run_groundedness_check(Path('deliverables/business_plan.md').read_text(encoding='utf-8'), Path('deliverables'), project='capstone'); print(json.dumps(s, indent=2))"
   ```

2. [USER] Read `deliverables/groundedness_report.md`. Gate rules (fail-closed):
   zero claims = FAIL; >10% ERROR entailments = FAIL; zero high-risk claims =
   FAIL; high-risk blocking rate > 5% = FAIL.
3. [USER] Decision point on FAIL: the plan was already submitted, so "fix"
   means either revising the deliverable text and re-running, or recording
   the failure honestly. Either is acceptable; silence is not.
4. [BUILD] Record PASS/FAIL + the high-risk blocking rate in `CLAUDE.md`;
   strike roadmap item 4.

**Verification (PowerShell):**

```powershell
Test-Path deliverables\claims.json; Test-Path deliverables\entailment.json; Test-Path deliverables\groundedness_report.md
```

All three `True`, report summary non-empty, and the checked-in
`business_plan.md` was NOT regenerated.

---

## Phase 4 — Rerank latency: make the decision, with data — **DONE (2026-08-12, decision: KEEP ON)**

> **Outcome:** flag plumbed; measured rerank cost ~26.6 s/query (30.6s vs
> 4.0s retrieval-only). Comparison ran against `verify2`, not `verify1` as
> written (verify1 was scored under the pre-fix phrase matcher and would
> confound the rerank effect with the judge change). Decision: **keep rerank
> ON** — the entire quality difference is h04, whose only both-numbers chunk
> rerank ranks 6th and no-rerank drops from the top-10 (→ WRONG_EVIDENCE).
> Durable side-finding: MRR@10/nDCG@10 IMPROVED on the broken run — never
> read them as answer-quality proxies. Tables: `EVAL_NOTES.md` / `HISTORY.md`.

**Why this matters.** Measured retrieval mean is 40.6 s = 70.6% of per-question
wall clock, chiefly the CPU cross-encoder (`RERANK_TOP_N=30`). `retrieval.py`
already has `use_rerank: bool = True` — but no caller passes it and no CLI
flag exists, so the knob has never been measurable. This is a DECISION with
data, not an optimization project.

1. [BUILD] Plumb the flag, no behavior change at defaults:
   - `rag.py`: `--no-rerank` on the `query` subparser → `pipeline.query` →
     `hybrid_search(..., use_rerank=...)`.
   - `eval/run.py`: `--no-rerank`, threaded into
     `eval/arms.py::ArmAHybridRAG`'s `hybrid_search` call. Record the setting
     in the results meta and the MD header so a no-rerank run can never be
     mistaken for a rerank run.
   - Fast tests: `hybrid_search(use_rerank=False)` returns RRF-ordered
     results and never loads the cross-encoder.
2. [USER] Plain terminal — separate cache dir is load-bearing (same
   cache-blindness hazard as Phase 2):

   ```powershell
   python eval\run.py --hard --holdout tuning --judge-runs 3 --judge-evidence own `
     --no-rerank --cache-dir data\answer_cache_norerank --run-id norerank1 --out-suffix norerank
   ```

3. [USER] Compare `_norerank` against Phase 2's `_verify1`: recall@10 (pages),
   MRR@10, nDCG@10, verdicts, critical errors, mean wall s/q. Decide: keep
   rerank / skip rerank / conditional (e.g. rerank only `--doc`-scoped
   queries).
4. [BUILD] Record the decision AND both runs' numbers in `CLAUDE.md`. If the
   decision changes the default path, it MUST land before Phase 6's freeze —
   the baseline must describe the shipped default.

**Verification:**

```powershell
python rag.py query "coffee shop break-even" --project capstone --no-rerank
```

Completes visibly faster with a cited answer; both tuning result files exist
with distinct suffixes; the decision paragraph is in `CLAUDE.md`.

---

## Phase 5 — SDK-ready bridge: `BRIDGE_BACKEND = "cli" | "sdk"` — **DONE (2026-08-05)**

> **Outcome:** shipped as specified with one correction to the spec itself —
> **the "honored `temperature=0`" payoff does not exist**: sampling params
> were removed from the Opus 4.7 generation onward and `claude-opus-5` /
> `claude-sonnet-5` return 400 on `temperature`, so `_call_sdk` accepts and
> DROPS it (forwarding it would fail every judge call). Double opt-in
> (`PDFRAG_BRIDGE=sdk` + `PDFRAG_ALLOW_API_KEY=1`), model-ID mapping, typed
> exceptions, synthesized envelope, one live SDK smoke, env vars removed
> after (verified — no freeze contamination). Default backend `cli`.

**BLOCKED until agent-lab lessons 00–08 are done** (see cross-project
dependency above). During execution, load the `claude-api` skill to verify
model IDs and pricing — never from memory.

**Why this matters.** Grounded (FastAPI + Supabase pgvector) will consume this
bridge via the SDK. The port gets real system-role separation (today system +
user are concatenated on stdin), an honored `temperature=0` for judges and
entailment (today ignored), typed exceptions instead of stdout sniffing, and
retry/backoff. The contract "plan limits, not paid API" survives because the
default backend stays `cli`. Template: `agent-lab/lab/client.py` — note it
has NO retry/backoff; do not copy that gap.

1. [BUILD] `config.py`:
   - `BRIDGE_BACKEND = os.environ.get("PDFRAG_BRIDGE", "cli")` (config.py has
     no `os` import today — add it).
   - `MODEL_IDS = {"sonnet": "claude-sonnet-5", "opus": "claude-opus-5", "haiku": "claude-haiku-4-5"}` —
     CLI aliases are NOT valid API model IDs; every SDK call maps through
     this. Verify current IDs via the `claude-api` skill before committing.
   - `SDK_MAX_RETRIES = 3`, `SDK_MAX_TOKENS = 16_000`,
     `MAX_CONTEXT_TOKENS = 37_500` (token twin of `MAX_CONTEXT_CHARS`).
2. [BUILD] Kill the config bypasses FIRST (they'd 404 in SDK mode):
   `compose_capstone.py:185/:242/:304` hardcoded `"opus"`/`"sonnet"` →
   `CLAUDE_MODEL_QUALITY`/`CLAUDE_MODEL_FAST`; `groundedness.py` model
   defaults (lines 212, 275, 480–481) → config constants.
3. [BUILD] `claude_bridge.py`: private `_call_sdk(model, system, user,
   timeout, temperature)` used by `call_claude` / `call_claude_json` when
   `BRIDGE_BACKEND == "sdk"`:
   - Lazy `import anthropic`; singleton
     `anthropic.Anthropic(max_retries=SDK_MAX_RETRIES)`; add `anthropic` to
     `requirements.txt`.
   - Real roles: `system=system`, `messages=[{"role":"user","content":user}]`.
   - `temperature=0.0` passed through when the caller passed `0.0`; omitted on
     the `_DEFAULT_TEMPERATURE` sentinel. No caller changes needed — they
     already pass the right values (that was the point of B4).
   - Typed exception mapping preserving every caller's `except` clauses:
     `anthropic.AuthenticationError` / `anthropic.RateLimitError` →
     `SessionLimitError`; other `anthropic.APIError` / connection errors →
     `ClaudeCLIError`. `_looks_like_limit` stdout-sniffing stays CLI-only.
   - **Auth inversion guard:** `_plan_auth_env()` strips `ANTHROPIC_API_KEY` —
     correct for CLI, fatal for SDK (which REQUIRES it). Strip only on the
     CLI path; the SDK path requires BOTH `PDFRAG_BRIDGE=sdk` AND
     `PDFRAG_ALLOW_API_KEY=1`, else raise `ClaudeCLIError` with a "this is
     metered API billing" message. A backend switch must never be able to
     silently start a bill.
   - CLI-era workarounds NOT applied on the SDK path: temp cwd (no
     subprocess), decode `errors="replace"`, missing-binary probe.
   - `call_claude_json` SDK branch: synthesize the envelope
     `{"result": text, "usage": {input_tokens, cache_read_input_tokens,
     cache_creation_input_tokens, output_tokens}}` so `total_input_tokens`
     and `eval/ablation_report.py` work unchanged.
   - `call_claude_agentic` stays CLI-only unconditionally (it drives Claude
     Code's agentic tools; no SDK equivalent) — one docstring line saying so.
4. [BUILD] Token counting, minimal scope: add
   `claude_bridge.count_input_tokens(system, user, model)` — SDK mode:
   `client.messages.count_tokens`; CLI mode: `len(text) // 4`. Route the
   cosmetic sites `pipeline.py:157` / `:198` through it; `summarize`'s
   single-pass branch uses `MAX_CONTEXT_TOKENS` via the helper in SDK mode
   only; the CLI branch keeps the char guard. Nothing else.
5. [BUILD] Tests (mock the SDK client; never hit the network): alias mapping
   lands in `create` kwargs; system passed as its own kwarg; `temperature=0.0`
   present / sentinel absent; `RateLimitError` → `SessionLimitError`; SDK
   mode without the double opt-in raises; default backend still takes the
   subprocess path; synthesized envelope feeds `total_input_tokens`.
6. [USER] One real SDK smoke (costs actual API money, cents):

   ```powershell
   $env:PDFRAG_BRIDGE="sdk"; $env:PDFRAG_ALLOW_API_KEY="1"; python rag.py query "test" --project capstone
   Remove-Item Env:PDFRAG_BRIDGE, Env:PDFRAG_ALLOW_API_KEY
   ```

   The `Remove-Item` is not optional — a leftover `PDFRAG_BRIDGE=sdk` would
   contaminate Phase 6's freeze.

**Verification (PowerShell):**

```powershell
python -m pytest tests\ -m "not slow"
python -c "import config; print(config.BRIDGE_BACKEND)"   # -> cli  (default unchanged)
```

---

## Phase 6 — Freeze: baseline, one holdout exposure, gate exit 0 — **DONE (2026-08-14, as run `freeze2`)**

> **Outcome:** two exposures, not one — and the second was earned. `freeze1`
> ran clean (holdout 10/10, zero holdout errors) but gate-failed on two
> tuning errors; h07's proved to be a false positive manufactured by
> label-only vote counting, and the investigation found `_judge_page_lookup`
> wrong in both directions. Per step 1's spirit ("no pending changes"), the
> freeze was WITHHELD rather than patched mid-run; the judge was fixed
> probe-first on tuning + planted probes only, then the re-run replayed
> freeze1's cached answers byte-identical so the delta is the judge fix and
> nothing else. `freeze2`: 24/25 EQUIVALENT, medians 5/5/5, holdout 10/10
> clean, sole error `FORMAT_FAIL=1` on h01 (correctly named, not
> gate-tracked, failure still visible at MRR 0.0). Baseline regenerated from
> freeze2; gate exit 0, zero warnings. Full account: `HISTORY.md` "Task 20".

**Why this matters.** These are the numbers Grounded's docs will quote. The
holdout gets looked at ONCE, here, after everything above has stabilized —
and strictly under the default (`cli`) backend, because that is the shipped
contract. Never run this phase with `PDFRAG_BRIDGE=sdk` set.

1. [USER] Confirm no pending changes to retrieval, prompts, or judge prompts.
   Plain terminal, full set (the one-time holdout run — the 10 holdout
   questions are being scored for the record, not for iteration):

   ```powershell
   python eval\run.py --hard --judge-runs 3 --judge-evidence own --run-id freeze1
   ```

2. [USER] Check the report: zero critical errors anywhere (tuning AND
   holdout); holdout verdicts recorded, never acted on.
3. [BUILD] Regenerate the baseline from this exact run and gate against it:

   ```powershell
   Copy-Item eval\results_hard.json eval\baseline.json
   python eval\gate.py --current eval\results_hard.json
   ```

   Exit 0. (The absolute floors and judge-outage checks run
   baseline-independently, so this is not vacuous self-comparison.)
4. [BUILD] `CLAUDE.md`: Recent Changes entry with the frozen numbers
   (EQUIVALENT count, medians, flip-rate, citation accuracy, wall s/q with
   the Phase 4 rerank decision noted), calibration summary, groundedness
   result, and "baseline frozen <date>, run `freeze1`".

**Verification (PowerShell):**

```powershell
python eval\gate.py --current eval\results_hard.json; echo "exit=$LASTEXITCODE"   # exit=0
python -m pytest tests\ -m "not slow"
```

---

## Definition of done

1. [x] ~~`eval/calibration_results.md` exists~~ — satisfied via the second
       arm: **the gap is documented** (anchors are `prior_verdict_mapping`
       remaps of the April 2026 judge's own verdicts; running measures
       agreement with a judge proven wrong; re-bootstrapping is circular —
       F29/F30; only human labels resolve it). Calibration deliberately not
       run; `calibration.json` untouched.
2. [x] Fresh tuning run: zero critical errors under majority vote — met by
       **`verify2`** (verify1's sole error was a phrase-matcher orthography
       artifact, adjudicated and fixed). `tools/probe_judge.py` passes — and
       now probes the rule judges and vote aggregation too.
3. [x] All three deliverable artifacts exist; **FAIL recorded** in `CLAUDE.md`
       (27.4% vs 5%, with the projection-genre reading); the checked-in plan's
       sha256 verified unchanged.
4. [x] `--no-rerank` on both entry points; both tuning runs on disk
       (`verify2` + `norerank`); decision **KEEP ON** + numbers in `CLAUDE.md`
       / `EVAL_NOTES.md`.
5. [x] `BRIDGE_BACKEND` switch works; default `cli`; SDK mode maps model IDs,
       separates the system role, retries, raises typed errors, requires the
       double opt-in; `call_claude_agentic` untouched CLI; hardcoded model
       strings eliminated; `anthropic` optional in `requirements.txt`; tests
       green. One spec correction: `temperature=0` is accepted and DROPPED —
       claude-opus-5 / claude-sonnet-5 reject sampling params with a 400, so
       "honors temperature=0" was never achievable on either backend.
6. [x] `eval/baseline.json` regenerated from run **`freeze2`** (full 25;
       holdout exposed twice — the second exposure sanctioned, after the
       probe-first judge fix; every fix designed on tuning + planted probes
       only); `eval/gate.py` exits 0 with zero warnings; fast suite 74/74;
       `CLAUDE.md` carries the quotable numbers.

## Hazards

- **`compose_capstone.py` overwrites the deliverable before gating** (Phase 3).
- **Answer-cache blindness to retrieval config** — any A/B on `use_rerank`
  needs `--cache-dir` + `--out-suffix` or it replays cached answers (Phases
  2 and 4).
- **Calibration anchors may encode pre-judgefix judge errors** — check
  provenance before treating a <80% score as judge failure (Phase 1).
- **SDK auth inversion** — the same env-var handling that protects CLI
  billing breaks SDK auth; the split must be per-backend and SDK must be
  double-opt-in (Phase 5).
- **Backend contamination of the freeze** — frozen numbers are CLI-mode
  numbers; a leftover `$env:PDFRAG_BRIDGE` from Phase 5 testing would
  silently change what Phase 6 measures.
- **Schedule risk:** Phase 5 blocks on the agent-lab learning pace. Phases
  1–4 don't — if lessons stall, run 1–4 to an interim gate-green state and
  leave 5–6 pending rather than freezing twice.
