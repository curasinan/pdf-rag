# Ablation build notes — traps that cost real time

Extracted from `CLAUDE.md` once the three-arm ablation finished, to keep the
project memory light. The study itself is in `ABLATION_WRITEUP.md`; this file is
only the things that would bite again if the ablation is re-run or extended.

The three-arm ablation (hybrid RAG vs whole-corpus vs agentic file search) is
finished; the result is in the next section and the writeup is
`ABLATION_WRITEUP.md`. What follows is only the things that would bite again.
Implementation detail lives in the code and in `tests/test_smoke.py` (55 tests).

### Eval ground truth

- **NFD/NFC gold-source mismatch.** `5 KPIs …Café…` is stored **NFD** in ChromaDB
  but labelled **NFC** in `questions_hard.json`, and `get_chunks_for_source` builds
  an exact Chroma `where` — so four gold entries (h01, h05, h06, one of h08's two)
  resolved to **zero** chunks silently, and `eval/oracle.py` had skipped them on
  every run it ever did. `eval/gold.py` now matches on a normalized index over
  *stored* strings and **raises `GoldSourceMissing`** instead of returning `[]`.
  Recall/MRR/nDCG and citation validation were never affected — they already
  NFC-normalize both sides.
- **Gold page sets are chunk-shaped, not fact-shaped.** They record where arm A's
  retriever found an answer, not where the fact is: invisible to arm A (its chunks
  span pages, so one overlap satisfies `_is_relevant_chunk`) and punishing to any
  arm citing the precise page. Six labels corrected (h02, h04, h05, h12, h14, h15);
  `tools/audit_gold_pages.py` screens the rest, but it also flags generic words and
  decoys, so read it with judgement.
- **`must_contain` page assertions are format-agnostic** (`_phrase_satisfied`) —
  `page(s) N` entries check the pages the answer actually cites, not substrings,
  because the pinned F10 format renders `[src, pages 7-8]`, which does not contain
  the literal `"page 8"` h01 demanded. Falls back to the substring test.
- **Percent representations unified** (`_percent_variants`): h13's gold is `32.5`
  but the workbook stores `0.325`. Only the ÷100 form is accepted — the inverse
  would let `72` satisfy h15's expected `7200`.

### Harness

- **Producer seam** (`eval/arms.py`). `run_eval`'s retrieval+generation block is
  one call to a pluggable producer returning a `Production`. Adding an arm is a
  class plus a registry line; everything downstream is arm-agnostic.
- **`retrieval_applicable` guards recall / MRR / nDCG.** These are *ranking*
  metrics. A non-ranking arm reporting them scores a trivially perfect "100%
  retrieval recall" — meaningless but authoritative-looking in a table. A
  non-ranking arm prints `n/a`, never `0.0%`, which reads as catastrophic.
- **`--judge-runs` used to be a silent no-op** — accepted, printed, then dropped,
  so any flip-rate conclusion compared two identical 3-run configs. Now threaded
  through `_judge`, and a test asserts it.
- **Checkpointing + answer cache** (`eval/cache.py`). Results were written once
  after the loop, so a session limit at question 20 lost twenty generations. Now
  appended per question to `eval/partial/{run_id}_{arm}.jsonl`; `--resume` skips
  them but **ERROR rows are retried, not inherited**, and errored productions are
  never cached. `SessionLimitError` aborts with resume instructions rather than
  scoring `"[generation failed]"` as an answer — otherwise an outage becomes a
  data point. Classification reads **stdout as well as stderr**: the CLI writes
  `Not logged in · Please run /login` to stdout with empty stderr.
- **`results_stem()` owns output naming** and every clause exists because two runs
  once shared a file: non-A arms get their own stem, `--only` forces `_partial` so
  a pilot can't be read as a complete run, and `--out-suffix` separates repeat
  seeds of the same questions.

### Arms B and C

- **Arm B must render through `pipeline._format_context`**, the same function arm
  A uses, so headers parse identically. Do **not** use `compose_capstone.dump_corpus`:
  its `[Pages [1, 2, 3]]` header has no source name and is the unparseable pre-F10
  shape, and its 200K default truncates 23 of 24 sources. Measured context:
  294,347 chars / 121 chunks / 24 sources, sha1 in the envelope as proof.
- **Arm C's text mirror is mandatory, not a convenience.** On this machine `Read`
  fails on every source file (no `pdftoppm`; DOCX/XLSX rejected as binary) and
  `Grep` on the PDFs returns **zero** hits for `"table turn"` — h01's literal
  ground truth — because the streams are Flate-compressed. Pointing an agent at
  `sources/capstone` measures poppler's absence, not architecture.
  `tools/build_mirror.py` builds it from `pdf_parser.extract_pages` (same
  extraction arm A ingests) and asserts all 121 chunks' text is present.
- **Sandbox** (`claude_bridge.assert_agentic_sandbox`). `questions_hard.json` holds
  every gold answer, so the agent must not reach the repo. Fails closed on a work
  dir inside the repo or any `CLAUDE.md` in an ancestor. Uses `--tools Read,Grep,Glob`
  (capability restriction, stronger than `--allowedTools`; Bash excluded so it
  cannot shell out to `pdftotext`) and **`--permission-mode default`, never
  `bypassPermissions`** — in `-p` mode a prompt cannot be answered, so an
  out-of-scope attempt fails visibly instead of silently succeeding.
- **Mirror lives outside the repo at `<repo-parent>/pdf-rag-ablation/`, not
  `%LOCALAPPDATA%`.** The Claude desktop app is MSIX-packaged, so `AppData/Local`
  is transparently redirected to `…/Packages/Claude_*/LocalCache/Local` — same path
  string, two physical directories, and a mirror built inside the app is invisible
  to the plain terminal arm C must run from. Containment checks use
  `Path.relative_to`, not `startswith`: `pdf-rag-ablation` prefixes `pdf-rag`.
- **`Production.citation_scope`** picks the validation universe. Arm C has no chunk
  set, so it validates against the full corpus rather than an empty list (which
  would score 0.0 precision for a correct answer) — making precision mean "cites a
  real (source, page)", not "faithful to shown context".
- **Run `tools/probe_agentic.py` from a plain terminal before trusting any arm C
  number** (envelope shape, sandbox leak, memory leak, citation parseability).

### CLI

- **Billing trap.** The user-scope environment holds a real 108-char
  `sk-ant-api03-…` key, and the CLI's auth precedence puts `ANTHROPIC_API_KEY`
  *ahead* of subscription OAuth in `-p` mode. Every call would have been metered
  API billing, violating this project's "plan limits, not the paid API" contract.
  `claude_bridge._plan_auth_env()` now strips it from every subprocess; escape
  hatch `PDFRAG_ALLOW_API_KEY=1`.
- A `claude` subprocess spawned inside a Claude Code session cannot authenticate
  until the CLI has been logged in from a plain terminal.
- `--setting-sources ""` is undocumented syntax; use `project,local` (which
  resolves to nothing from the mirror). Bisection exonerated it as the auth cause —
  `tools/diagnose_agentic_auth.py` does that bisection.
- **Token accounting**: `usage.input_tokens` reads near-zero when a prompt is
  cache-served (arm A measured **1** against a true **44,086**). Always sum
  `input + cache_read + cache_creation` — `claude_bridge.total_input_tokens`.

### Citation parsing

Three bugs found by running the arm C probe for real; all would have corrupted
precision *differentially*, since arms differ in how chatty they are. A repeated
citation was deduplicated without claiming its span, letting a looser pattern
match inside the second occurrence; the inline pattern allowed whitespace-only
separation, so "the RevPASH section on page 5" parsed; and source classes were
ASCII-only and capital-initial, so `5 KPIs …Café…` never parsed in prose (3 of 24
sources start with a digit, one carries an accent). Unbracketed patterns now need
≥4 alphabetic characters. Residual: "As of Q3, page 2" still parses but fails
source validation, so it costs precision rather than inventing a citation.

### Judge evidence policy — moves the metric more than the architecture does

Scored the *same cached* arm C answers three ways, the pilot got 1/3 to 2/3
EQUIVALENT and groundedness 1, 2 or 4 depending only on `--judge-evidence`
(full table in `ABLATION_WRITEUP.md`). The rule that came out of it:

- **`corpus` for any cross-arm comparison** — label-independent, byte-identical
  across arms, and the corpus is the ground truth.
- **`own` only for the arm-A baseline**, because it reproduces the pre-ablation
  faithfulness semantics `eval/baseline.json` is built on. An arm with no shown
  context gets an EMPTY block here and a bogus groundedness of 1.
- **`gold` for neither.** It punishes an arm that correctly reads *beyond* the
  chunk-shaped label (h07: arm C cited Briefing Doc p1/p7, which genuinely carry
  a second break-even formula and Gross Margin; the label lists only p4-5).

---

### Reseeding a generation (moved from CLAUDE.md, Aug 2026)

Two traps, both load-bearing, from the second generation seed
(`eval/seed_stability_seed2.md`; headline table kept in CLAUDE.md):

- **Reseed the stratum, not the discordant set.** The four questions carrying the
  whole A-vs-C delta were *selected* for being extreme, so regression to the mean
  shrinks the gap whether or not the effect is real. The run must cover all six
  `page_lookup` questions — h03/h04 are the same-type controls, and without them
  the drift numbers are uninterpretable.
- **Use a separate `--cache-dir`, never `--no-cache`.** The answer cache is
  content-addressed, so a reseed on the default cache replays seed 1 and looks
  healthy while measuring nothing. A separate dir also keeps seed 2 cached, so
  re-judging is free. `--out-suffix` stops it overwriting seed 1 and the July
  pilot files.

The same cache-blindness trap applies to any A/B on retrieval config — it is why
COMPLETION_PLAN Phases 2 and 4 both mandate a separate `--cache-dir`.

---
