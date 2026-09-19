"""Smoke tests for the RAG pipeline.

Goals
=====
- Verify the major code paths import and run without exceptions.
- Catch obvious regressions to retrieval, project filtering, per-source quota,
  HyDE heuristics, and idempotent ingest.
- Keep tests fast (no Claude CLI calls, no docling re-ingest). The slow eval
  test is opt-in via `pytest -m slow`.

These tests assume the capstone project has already been ingested (which it
has after the Weekend-2 docling re-ingest). If you wipe the corpus, re-run
`python batch_ingest.py sources/capstone --project capstone` before running
tests.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent


# ── Imports + project filter ────────────────────────────────────────


def test_all_modules_import():
    """No circular imports, no syntax errors."""
    import config            # noqa: F401
    import logging_setup     # noqa: F401
    import claude_bridge     # noqa: F401
    import embeddings        # noqa: F401
    import vectorstore       # noqa: F401
    import bm25              # noqa: F401
    import reranker          # noqa: F401
    import retrieval         # noqa: F401
    import hyde              # noqa: F401
    import pdf_parser        # noqa: F401
    import prompts           # noqa: F401
    import pipeline          # noqa: F401


def test_capstone_corpus_present():
    """The capstone project should have docs after the Weekend-2 re-ingest."""
    from vectorstore import list_documents, list_projects
    projects = list_projects()
    assert "capstone" in projects, f"capstone project missing; have: {projects}"
    docs = list_documents(project="capstone")
    assert len(docs) >= 20, f"expected ≥20 capstone docs, got {len(docs)}"


def test_project_filter_isolates():
    """Querying a non-existent project returns nothing; capstone returns chunks."""
    from retrieval import hybrid_search
    capstone = hybrid_search("coffee shop break-even", top_k=5,
                             project="capstone", use_hyde=False)
    assert len(capstone) > 0
    assert all(c.get("project", "capstone") == "capstone" for c in capstone)

    nowhere = hybrid_search("coffee shop break-even", top_k=5,
                            project="nonexistent_project_zzz", use_hyde=False)
    assert nowhere == []


# ── Per-source quota ────────────────────────────────────────────────


def test_min_per_source_quota():
    """When a multi-chunk source wins top-1, the quota guarantees ≥2 chunks for it."""
    from retrieval import hybrid_search
    chunks = hybrid_search("five KPIs every coffee shop manager should track",
                           top_k=10, project="capstone", use_hyde=False,
                           min_per_source=2)
    by_source: dict[str, int] = {}
    for c in chunks:
        by_source[c["source"]] = by_source.get(c["source"], 0) + 1
    # Whichever source ranks #1 should have at least 2 chunks (when 2 exist)
    top_source = chunks[0]["source"]
    assert by_source[top_source] >= 2, (
        f"per-source quota failed: top source {top_source!r} got {by_source[top_source]} chunks"
    )


def test_quota_disabled_when_min_one():
    """min_per_source=1 yields no quota effect — pure rerank order."""
    from retrieval import hybrid_search
    chunks = hybrid_search("test query", top_k=5, project="capstone",
                           use_hyde=False, min_per_source=1)
    assert isinstance(chunks, list)


# ── HyDE heuristic ──────────────────────────────────────────────────


def test_hyde_skips_short_queries():
    from hyde import should_use_hyde
    assert should_use_hyde("find foo") is False
    assert should_use_hyde("what page is X on?") is False
    assert should_use_hyde('"exact phrase"') is False


def test_hyde_accepts_real_queries():
    from hyde import should_use_hyde
    assert should_use_hyde("how does break-even analysis work for coffee shops") is True
    assert should_use_hyde("compare the strategies for coffee shop loyalty programs") is True


# ── Idempotency / cache key ─────────────────────────────────────────


def test_chunker_version_stored_in_metadata():
    """Phase-3 cache key fields are populated. We don't pin chunker_version to
    the current constant because bumping ``CHUNKER_VERSION`` in config.py is
    the *correct* way to mark the cache stale before a planned re-ingest;
    asserting equality here would fail every time we bump and forget to
    re-ingest the test corpus, which isn't the contract the cache key is
    meant to enforce. We do assert metadata presence and shape so a missing
    field (the actual regression mode) trips the test."""
    from vectorstore import get_source_metadata
    docs_to_check = ["Calculating Your Break Even Point",
                     "5 KPIs Every Clever Café Manager Should Track"]
    found_any = False
    for src in docs_to_check:
        meta = get_source_metadata(src, project="capstone")
        if meta is None:
            continue  # name might be NFD-encoded for the Café file
        found_any = True
        assert isinstance(meta.get("chunker_version"), int), (
            f"chunker_version missing or non-int for {src!r}: {meta!r}"
        )
        assert meta.get("embedding_model"), f"embedding_model missing for {src!r}"
        assert meta.get("file_sha256"), f"file_sha256 missing for {src!r}"
    assert found_any, "no matching docs found"


# ── Where-clause helper edge cases ──────────────────────────────────


def test_build_where_helper():
    from vectorstore import _build_where
    assert _build_where() is None
    assert _build_where(source="X") == {"source": "X"}
    assert _build_where(project="P") == {"project": "P"}
    w = _build_where(source="X", project="P")
    assert w == {"$and": [{"source": "X"}, {"project": "P"}]}


# ── Chunker correctness ─────────────────────────────────────────────


def test_section_aware_chunker_units():
    from pdf_parser import _split_units
    units = _split_units("## Section A\nbody A\n\n## Section B\nbody B")
    assert len(units) == 2
    assert units[0][0] == "section"
    assert units[1][0] == "section"


def test_chunker_respects_min_size():
    """A single tiny page shouldn't yield a tiny chunk; the chunker keeps absorbing."""
    from pdf_parser import chunk_pages
    pages = [
        {"page_num": 1, "text": "## A\nshort"},
        {"page_num": 2, "text": "## B\nalso short"},
        {"page_num": 3, "text": "## C\n" + ("filler " * 200)},
    ]
    chunks = chunk_pages(pages, source="test")
    # First chunk should not be just "## A\nshort" — it should absorb at least until
    # MIN_CHUNK_CHARS or end of doc
    assert len(chunks[0]["text"]) > 100, f"first chunk too small: {len(chunks[0]['text'])}"


# ── CLI smoke (no Claude calls) ─────────────────────────────────────


def test_rag_help_works():
    """`python rag.py --help` exits 0 and lists subcommands.

    The 30 s timeout this used to carry was below the measured cold-start cost:
    argparse cannot print help until `rag.py` has imported the pipeline, which
    pulls torch + chromadb + sentence-transformers, and that takes ~34 s cold on
    this machine (a few seconds warm). So the test passed whenever the OS file
    cache happened to be warm from an earlier test and failed on a cold run —
    a flake that reports "your change broke the CLI" when nothing did.
    """
    result = subprocess.run(
        [sys.executable, str(ROOT / "rag.py"), "--help"],
        capture_output=True, text=True, encoding="utf-8", timeout=180,
    )
    assert result.returncode == 0
    assert "ingest" in result.stdout
    assert "projects" in result.stdout  # Phase 0 addition


def test_rag_projects_command():
    """`python rag.py projects` exits 0 and shows capstone.

    Same cold-start floor as ``test_rag_help_works`` plus a ChromaDB open, so 60 s
    was only ever a coin flip on a cold cache.
    """
    result = subprocess.run(
        [sys.executable, str(ROOT / "rag.py"), "projects"],
        capture_output=True, text=True, encoding="utf-8", timeout=180,
    )
    assert result.returncode == 0
    assert "capstone" in result.stdout


# ── Weekend-3: regression gate, holdout split, groundedness ─────────


def test_regression_gate_imports_and_passes_self():
    """The gate exits 0 when current == baseline (sanity check). Fast: no LLM."""
    sys.path.insert(0, str(ROOT))
    from eval.gate import regression_gate
    baseline = ROOT / "eval" / "baseline.json"
    if not baseline.exists():
        pytest.skip("eval/baseline.json missing; gate is unverifiable in this checkout")
    # Compare baseline against itself — should pass.
    exit_code = regression_gate(current_path=baseline, baseline_path=baseline)
    assert exit_code == 0, "gate failed when comparing baseline to itself"


def test_holdout_split_balanced():
    """questions_hard.json must have 10 holdout / 15 tuning, 2 per type."""
    from collections import Counter
    qs = json.loads((ROOT / "eval" / "questions_hard.json").read_text(encoding="utf-8"))
    holdout = [q for q in qs if q.get("holdout")]
    tuning = [q for q in qs if not q.get("holdout")]
    assert len(holdout) == 10, f"expected 10 holdout, got {len(holdout)}"
    assert len(tuning) == 15, f"expected 15 tuning, got {len(tuning)}"
    types = Counter(q["question_type"] for q in holdout)
    assert all(c >= 2 for c in types.values()), f"holdout types unbalanced: {types}"


def test_groundedness_module_imports():
    """G1 module imports cleanly and the high-risk filter recognizes Financial."""
    sys.path.insert(0, str(ROOT))
    from groundedness import (
        extract_claims, entail_claim, run_groundedness_check, _is_high_risk,
    )
    assert _is_high_risk("Financial Plan") is True
    assert _is_high_risk("Risk Analysis") is True
    assert _is_high_risk("Marketing Strategy") is False


def test_claude_bridge_temperature_signature():
    """B4: call_claude accepts ``temperature`` keyword argument."""
    sys.path.insert(0, str(ROOT))
    import inspect
    from claude_bridge import call_claude
    params = inspect.signature(call_claude).parameters
    assert "temperature" in params, "claude_bridge.call_claude missing temperature param"


# ── Ablation Phase 0: gold resolution + label-defect fixes ──────────


def test_gold_source_resolves_across_unicode_normalization():
    """The Café source is stored NFD in ChromaDB but labelled NFC in the
    question file, so the old exact-match lookup returned zero gold chunks for
    h01/h05/h06/h08 — silently, on every oracle run ever made."""
    sys.path.insert(0, str(ROOT))
    from eval.gold import gold_chunks_for_question, resolve_source, GoldSourceMissing

    nfc_name = "5 KPIs Every Clever Café Manager Should Track"      # é as one codepoint
    nfd_name = "5 KPIs Every Clever Café Manager Should Track"     # e + combining acute

    assert resolve_source(nfc_name, "capstone") is not None, "NFC label must resolve"
    assert resolve_source(nfd_name, "capstone") is not None, "NFD label must resolve"

    chunks = gold_chunks_for_question(
        [{"source": nfc_name, "pages": [8]}], project="capstone"
    )
    assert chunks, "gold chunks must resolve for the NFD-stored source"

    # Negative questions legitimately have no gold passage.
    assert gold_chunks_for_question([], project="capstone") == []

    # A genuinely missing source must fail loudly, not return [].
    with pytest.raises(GoldSourceMissing):
        gold_chunks_for_question(
            [{"source": "No Such Document", "pages": [1]}], project="capstone"
        )


def test_page_lookup_phrase_is_citation_format_agnostic():
    """A ``must_contain`` page assertion must test *which page the answer
    identifies*, not which prose spelling it used. The pinned F10 citation
    format renders ``[src, pages 7-8]``, which does not contain the literal
    substring "page 8" — under the old test that failed a correct answer."""
    sys.path.insert(0, str(ROOT))
    from eval.run import _phrase_satisfied, _answer_pages

    equivalent = [
        "KPI #5 is Table Turn Time, defined on page 8.",
        "Table Turn Time [5 KPIs Every Clever Café Manager Should Track, page 8]",
        "Table Turn Time [5 KPIs Every Clever Café Manager Should Track, pages 7-8]",
        "Table Turn Time (see p. 8).",
        "Discussed on pp. 7-8 of the KPI guide.",
    ]
    for ans in equivalent:
        assert _phrase_satisfied("page 8", ans.lower(), _answer_pages(ans)), ans

    for wrong in ["Table Turn Time, defined on page 3.", "KPI #5 is Table Turn Time."]:
        assert not _phrase_satisfied("page 8", wrong.lower(), _answer_pages(wrong)), wrong

    # Non-page phrases are substrings, retried with word separators folded.
    ans = "KPI #5 is Table Turn Time."
    assert _phrase_satisfied("table turn", ans.lower(), _answer_pages(ans))
    assert not _phrase_satisfied("revpash", ans.lower(), _answer_pages(ans))


def test_page_lookup_judge_separates_abstention_from_fabrication():
    """``must_contain`` is a content-PRESENCE proxy, so all-miss is the union of
    {asserted something wrong} and {asserted nothing}: freeze1's honest h01
    abstention and a planted fabrication scored byte-identical 1/1/1 +
    WRONG_EVIDENCE. The floor for an abstention is FORMAT_FAIL — still a named
    relevance-1 non-answer, never NONE — and only a wrong ASSERTION earns the
    accusing label. Anchored on context-lack wording, never first-person
    inability: norerank h04 hedges "I can't pinpoint a single page number"
    around a confidently wrong worked example and must keep firing."""
    sys.path.insert(0, str(ROOT))
    from eval.run import _judge_page_lookup

    mc = ["table turn", "page 8"]

    def rule(ans):
        out = _judge_page_lookup(ans, mc, "exp", "q", "ev")
        return out["critical_errors"], out["relevance"]

    # Honest abstention (freeze1 h01's shape) → FORMAT_FAIL, not an accusation.
    abstain = ("The provided context doesn't actually define KPI #5 — the pages "
               "where it would be defined aren't included.")
    assert rule(abstain) == (["FORMAT_FAIL"], 1)

    # Confident fabrication, with or without a page → WRONG_EVIDENCE, never
    # FORMAT_FAIL (a page-free fabrication must not read as an abstention).
    fab = "The fifth KPI is Instagram Follower Count, discussed on page 4."
    assert rule(fab) == (["WRONG_EVIDENCE"], 1)
    fab_nopage = "The guide's fifth KPI is Customer Loyalty Percentage."
    assert rule(fab_nopage) == (["WRONG_EVIDENCE"], 1)

    # First-person page-granularity hedge is NOT an abstention: content phrases
    # all miss and the accusation stands (norerank h04's must-keep-firing case).
    hedged_wrong = ("I can't pinpoint a single page number, but the metric is "
                    "Instagram Follower Count, shown on page 4.")
    assert rule(hedged_wrong) == (["WRONG_EVIDENCE"], 1)


def test_page_lookup_judge_catches_a_fabricated_page():
    """The single defect a page_lookup question exists to catch — right entity,
    wrong page — produced NO error before Aug 2026 (3/3/3 + NONE). A missed
    ``page N`` assertion on an answer that cites pages and does not abstain is a
    wrong-page claim → CITATION_WRONG. Chunk-grain citations covering the gold
    page satisfy BEFORE any accusation is considered, so h06's ceiling (an
    answer that can only cite pages 1-3 for a fact on page 2) stays a ceiling."""
    sys.path.insert(0, str(ROOT))
    from eval.run import _judge_page_lookup

    mc = ["table turn", "page 8"]

    def rule(ans):
        out = _judge_page_lookup(ans, mc, "exp", "q", "ev")
        return out["critical_errors"], out["relevance"]

    wrong_page = ("KPI #5 is Table Turn Time. It is defined on page 3 "
                  "[5 KPIs Every Clever Café Manager Should Track, page 3].")
    assert rule(wrong_page) == (["CITATION_WRONG"], 2)

    # Honest hedged partial: right entity, page abstained → incomplete, no error.
    hedged = ("KPI #5 relates to table-turn speed, but its page number is not "
              "in the supplied context.")
    assert rule(hedged) == (["NONE"], 3)

    # Right entity, no page cited at all: incomplete, not a wrong-page claim.
    no_page = "KPI #5 is Table Turn Time."
    assert rule(no_page) == (["NONE"], 3)

    # Chunk-grain range covering the gold page satisfies the assertion outright.
    coarse = ("KPI #5 is Table Turn Time "
              "[5 KPIs Every Clever Café Manager Should Track, pages 7-8].")
    out = _judge_page_lookup(coarse, ["page 8"], "exp", "q", "ev",
                             n_runs=0)  # all satisfied → LLM path; n_runs=0 keeps it offline
    assert out["critical_errors"] == ["NONE"]


def test_critical_error_votes_are_span_aware():
    """A majority must be a majority ON A SPAN. freeze1's sole gate blocker was
    label-only counting: two runs accused two disjoint spans of h07's answer,
    neither span twice, yet counts['CITATION_WRONG'] == 2 blocked the gate.
    Overlapping windows of one span still convict; bare-label legacy rows
    (empty quotes, fail-open) re-aggregate byte-identically as wildcards."""
    sys.path.insert(0, str(ROOT))
    import eval.run as R

    cand = ("The first paragraph makes one claim about margins. "
            "A completely different paragraph cites the briefing document.")

    def scripted(errors, quotes):
        return {"relevance": 5, "groundedness": 5, "citation_accuracy": 5,
                "critical_errors": errors, "critical_error_quotes": quotes,
                "short_rationale": "scripted"}

    def aggregate(runs):
        orig = R._judge_once
        it = iter(runs)
        R._judge_once = lambda *a, **k: next(it, None)
        try:
            return R._judge_llm_aggregated("q", "ev", "exp", cand, n_runs=len(runs))
        finally:
            R._judge_once = orig

    disjoint = aggregate([
        scripted(["NONE"], []),
        scripted(["CITATION_WRONG"],
                 [["CITATION_WRONG", "one claim about margins"]]),
        scripted(["CITATION_WRONG"],
                 [["CITATION_WRONG", "cites the briefing document"]]),
    ])
    assert disjoint["critical_errors"] == ["NONE"]

    overlapping = aggregate([
        scripted(["CITATION_WRONG"],
                 [["CITATION_WRONG", "first paragraph makes one claim"]]),
        scripted(["CITATION_WRONG"],
                 [["CITATION_WRONG", "makes one claim about margins"]]),
        scripted(["NONE"], []),
    ])
    assert overlapping["critical_errors"] == ["CITATION_WRONG"]

    legacy = aggregate([
        scripted(["CITATION_WRONG"], []),
        scripted(["CITATION_WRONG"], []),
        scripted(["NONE"], []),
    ])
    assert legacy["critical_errors"] == ["CITATION_WRONG"]


def test_must_contain_phrase_is_separator_agnostic():
    """A ``must_contain`` phrase must test the claim, not the hyphen. h01's two
    generation seeds wrote "table turn time" and "table-turn speed" — the same
    claim — and scored 3 vs 1+WRONG_EVIDENCE, because ``must_contain`` collapses
    to a gate-blocking error only when EVERY phrase misses."""
    sys.path.insert(0, str(ROOT))
    from eval.run import _phrase_satisfied, _answer_pages

    for ans in [
        "KPI #5 relates to table-turn speed.",       # hyphen
        "KPI #5 relates to table turn speed.",       # plain space
        "KPI #5 relates to table  turn speed.",      # doubled space
        "KPI #5 relates to table‑turn speed.",  # non-breaking hyphen
        "KPI #5 relates to table turn speed.",  # non-breaking space
    ]:
        assert _phrase_satisfied("table turn", ans.lower(), _answer_pages(ans)), ans

    # Folding separators must not invent matches: it may only bridge a
    # separator, never insert or delete a character.
    for wrong in [
        "KPI #5 relates to seating speed.",
        "The table shows the turn ratio.",  # both words, wrong order
        "Turnover is discussed elsewhere.",
    ]:
        assert not _phrase_satisfied("table turn", wrong.lower(), _answer_pages(wrong)), wrong


def _hash_one(src: str, tag: str) -> str:
    """Compile a standalone function from source and hash it via code_hash."""
    sys.path.insert(0, str(ROOT))
    from tracing import code_hash
    import tempfile

    path = Path(tempfile.gettempdir()) / f"_jch_{tag}.py"
    path.write_text(src, encoding="utf-8")
    g: dict = {}
    exec(compile(src, str(path), "exec"), g)
    return code_hash((("f", g["f"]),))


def test_judge_code_hash_moves_on_logic_and_not_on_prose():
    """judge_prompt_hash covers the rubric TEXT only, so every judge decision made
    in Python was invisible to eval/gate.py. Twice that hid a real scoring change:
    the union->majority critical-error vote (6 blocking errors -> 0) and
    _phrase_satisfied learning to fold separators (h01 DIFFERENT 1/1/1 -> PARTIAL
    3/3/3). Both left judge_prompt_hash at ba29d7420a62.

    The hash must therefore move on a logic edit and hold still for prose, because
    this repo is roughly three-quarters docstring by volume and a gate that cries
    wolf gets ignored."""
    old = "def f(p, a):\n    return p in a\n"
    new = "def f(p, a):\n    if p in a:\n        return True\n    return p.strip() in a\n"
    new_prose = (
        'def f(p, a):\n'
        '    """A long new docstring explaining at length why this exists,\n'
        '    with references to incident h01."""\n'
        '    # an added comment\n'
        '    if p in a:      # trailing comment\n'
        '        return True\n'
        '    return p.strip() in a\n'
    )
    h_old, h_new, h_prose = (_hash_one(old, "old"), _hash_one(new, "new"),
                             _hash_one(new_prose, "prose"))
    assert h_old != h_new, "a logic change must move the hash"
    assert h_new == h_prose, "docstrings/comments/formatting must NOT move the hash"


def test_code_hash_is_stable_across_processes():
    """_VALID_ERRORS is a set, and Python randomizes string hashing per process, so
    repr() of a set of strings differs run to run. Unsorted, the hash would change
    on every invocation and the gate's warning would fire forever — worse than no
    warning at all. Two subprocesses with different PYTHONHASHSEED must agree."""
    snippet = (
        "import sys; sys.path.insert(0, r'%s')\n"
        "from tracing import code_hash\n"
        "print(code_hash(((\"S\", {'HALLUCINATION','CITATION_WRONG','NONE',"
        "'WRONG_EVIDENCE','FORMAT_FAIL','OVER_REFUSAL'}),)))\n" % ROOT
    )
    out = []
    for seed in ("0", "12345"):
        env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONIOENCODING": "utf-8"}
        r = subprocess.run([sys.executable, "-c", snippet], capture_output=True,
                           text=True, env=env, cwd=str(ROOT))
        assert r.returncode == 0, r.stderr
        out.append(r.stdout.strip())
    assert out[0] == out[1], f"set ordering leaked into the hash: {out}"


def test_code_fingerprint_is_regex_flag_sensitive_and_fails_loud():
    """A compiled regex carries its flags separately from .pattern, so hashing the
    pattern string alone is blind to a dropped re.IGNORECASE — which would silently
    change what _PAGE_ASSERTION_RE matches. And an unrecognised symbol type must
    RAISE: skipping it would reintroduce the exact blindness this hash removes."""
    sys.path.insert(0, str(ROOT))
    import re as _re
    from tracing import code_hash

    with_flag = _re.compile(r"^pages?\s*(\d+)$", _re.IGNORECASE)
    without = _re.compile(r"^pages?\s*(\d+)$")
    assert with_flag.pattern == without.pattern      # the trap
    assert code_hash((("R", with_flag),)) != code_hash((("R", without),))

    with pytest.raises(TypeError):
        code_hash((("d", {"unsupported": "mapping"}),))


def test_judge_code_registry_covers_the_whole_judge_surface():
    """The registry is the one place that can silently under-cover. page_lookup is a
    HYBRID — the rule decides 1-vs-3 and the LLM only resolves 4-vs-5 — so 15 of the
    25 hard questions route through rule code and both hashes are load-bearing on
    six of them. _expand_pages lives in citations.py, not eval/run.py, so a
    module-scoped enumeration would silently drop it."""
    sys.path.insert(0, str(ROOT))
    from eval.run import _JUDGE_CODE_SYMBOLS, judge_code_hash

    names = {n for n, _ in _JUDGE_CODE_SYMBOLS}
    required = {
        "_judge", "_judge_page_lookup", "_judge_numeric", "_judge_negative",
        "_phrase_satisfied", "_collapse_separators", "_answer_pages", "_expand_pages",
        "_PAGE_ASSERTION_RE", "_WORD_SEPARATOR_RE", "_extract_numbers",
        "_percent_variants", "_REF_TOKEN_RE", "_NUM_RE", "_NEGATIVE_PHRASES",
        "_judge_once", "_judge_llm_aggregated", "_parse_judge_json",
        "_quote_is_in_candidate", "_flip_rate", "_VALID_ERRORS",
        "_verdict_from_relevance",
    }
    assert required <= names, f"registry lost coverage of: {sorted(required - names)}"
    assert len(names) == len(_JUDGE_CODE_SYMBOLS), "duplicate name in registry"

    # The cross-module edge is the one a refactor silently drops.
    import inspect
    mods = {getattr(o, "__module__", None) for _, o in _JUDGE_CODE_SYMBOLS
            if inspect.isfunction(o)}
    assert "citations" in mods, "cross-module judge helper no longer covered"

    assert len(judge_code_hash()) == 12


def test_gate_hash_drift_warns_in_every_asymmetric_state(capsys):
    """Four states, and the silent one must stay silent. The three-branch original
    was duplicated per field once and the copy shipped with the
    'baseline predates the field' arm missing — the single case that matters most
    when a field is new. One helper, called twice, cannot drift apart."""
    sys.path.insert(0, str(ROOT))
    from eval.gate import _warn_hash_drift

    for cur, base, expect in [("a", "a", False), ("b", "a", True),
                              (None, "a", True), ("a", None, True), (None, None, False)]:
        capsys.readouterr()
        _warn_hash_drift("judge_code_hash", "judge code", cur, base)
        got = "WARN" in capsys.readouterr().out
        assert got is expect, f"cur={cur} base={base}: expected warn={expect}"


def test_judge_code_hash_reaches_every_envelope_write_site():
    """A field written on only some paths produces a silently inconsistent artifact
    — the same class of defect this hash exists to catch. run_eval writes the hash
    into the results envelope, the per-question record (so --resume can tell which
    inherited rows this run's judge code scored), and the trace versions dict."""
    src = (ROOT / "eval" / "run.py").read_text(encoding="utf-8")
    assert src.count('"judge_code_hash": jc_hash') == 3, (
        "expected judge_code_hash on all three write sites "
        "(envelope, per-question record, trace versions)"
    )
    assert "jc_hash = judge_code_hash()" in src


def test_numeric_judge_accepts_either_percent_representation():
    """h13's gold is 32.5/30.5 but the workbook stores 0.325/0.305. Both must
    score the same, without letting 72 satisfy an expected 7200 (h15)."""
    sys.path.insert(0, str(ROOT))
    from eval.run import _judge_numeric

    assert _judge_numeric("COGS is 32.5% in 2026, 30.5% by 2030", [32.5, 30.5])["relevance"] == 5
    assert _judge_numeric("Inputs shows 0.325 and 0.305", [32.5, 30.5])["relevance"] == 5
    assert _judge_numeric("COGS is 45% then 40%", [32.5, 30.5])["relevance"] == 1

    # No x100 direction: decimal decoys must NOT satisfy large expected values.
    assert _judge_numeric("the ratio was 72.00 and 5.22", [7200, 522])["relevance"] == 1
    assert _judge_numeric("fixed costs $7,200 and revenue $522", [7200, 522])["relevance"] == 5

    # F13 regression: page references still must not supply answer numbers.
    r = _judge_numeric("I could not find it; see pages 30-32", [32.5, 30.5])
    assert r["relevance"] == 1 and r["critical_errors"] == ["FORMAT_FAIL"]


def test_h14_gold_pages_include_the_page_with_the_answer():
    """The $0.79 breakdown is printed on page 8; the old label stopped at 7."""
    sys.path.insert(0, str(ROOT))
    questions = json.loads(
        (ROOT / "eval" / "questions_hard.json").read_text(encoding="utf-8")
    )
    h14 = next(q for q in questions if q["id"] == "h14")
    pages = h14["must_cite_sources"][0]["pages"]
    assert 8 in pages, "h14 gold must include page 8, where the total is printed"


# ── Ablation Phase 1: producer seam, cache, checkpoint ──────────────


def test_judge_runs_is_actually_threaded():
    """``--judge-runs`` was accepted, echoed in the banner, and then dropped —
    every run used DEFAULT_JUDGE_RUNS. CLAUDE.md advertised it as working."""
    sys.path.insert(0, str(ROOT))
    import inspect
    from eval.run import _judge, _judge_page_lookup, run_eval

    assert "n_runs" in inspect.signature(_judge).parameters
    assert "n_runs" in inspect.signature(_judge_page_lookup).parameters
    # ...and the value must actually reach the aggregator, not just be accepted.
    assert inspect.getsource(_judge).count("n_runs=n_runs") >= 2
    assert "n_runs=judge_runs" in inspect.getsource(run_eval)


def test_producer_registry_and_contract():
    sys.path.insert(0, str(ROOT))
    from eval.arms import make_producer, Production

    p = make_producer("A", project="capstone", top_k=10)
    assert p.name == "A_hybrid_rag"
    assert len(p.config_hash()) == 12
    # config_hash must be stable across calls or the answer cache thrashes.
    assert p.config_hash() == make_producer("A", project="capstone", top_k=10).config_hash()
    # ...and sensitive to retrieval config, or a stale answer survives a tuning change.
    assert p.config_hash() != make_producer("A", project="capstone", top_k=5).config_hash()

    with pytest.raises(ValueError):
        make_producer("Z", project="capstone", top_k=10)

    # Default must be conservative: an arm that does not rank may not claim
    # retrieval metrics.
    assert Production(answer="x").retrieval_applicable is False


def test_answer_cache_round_trip_and_never_caches_errors(tmp_path):
    sys.path.insert(0, str(ROOT))
    from eval.arms import make_producer, Production
    from eval.cache import AnswerCache

    p = make_producer("A", project="capstone", top_k=10)
    cache = AnswerCache(tmp_path)
    key = cache.key_for(p, "h01", "Question?", "opus", "ph1")

    assert cache.load(p, "h01", key) is None
    cache.store(p, "h01", key, "Question?", Production(
        answer="A1", context_chunks=[{"text": "t", "source": "s", "pages": "[1]"}],
        evidence_text="ev", retrieval_applicable=True,
    ))
    hit = cache.load(p, "h01", key)
    assert hit.answer == "A1" and hit.telemetry["cache_hit"] is True
    assert hit.retrieval_applicable is True

    # A different question text must not hit the same entry.
    assert cache.load(p, "h01", cache.key_for(p, "h01", "Other?", "opus", "ph1")) is None

    # An outage must never become a permanent cached answer.
    ekey = cache.key_for(p, "h02", "Q2", "opus", "ph1")
    cache.store(p, "h02", ekey, "Q2", Production(answer="", error="boom"))
    assert cache.load(p, "h02", ekey) is None


def test_checkpoint_resume_retries_errors_and_survives_truncation(tmp_path):
    """A crash mid-write must not corrupt resume, and an ERROR row must be
    retried rather than frozen into the final results."""
    sys.path.insert(0, str(ROOT))
    from eval.cache import Checkpoint

    cp = Checkpoint(tmp_path / "part.jsonl")
    cp.append({"id": "h01", "verdict": "EQUIVALENT"})
    cp.append({"id": "h02", "verdict": "ERROR"})
    cp.append({"id": "h03", "verdict": "PARTIAL"})
    with (tmp_path / "part.jsonl").open("a", encoding="utf-8") as fh:
        fh.write('{"id": "h04", trunca')          # killed mid-write

    done = cp.load()
    assert sorted(done) == ["h01", "h03"], "ERROR and truncated rows must not count as done"
    assert sorted(cp.load(include_errors=True)) == ["h01", "h02", "h03"]


def test_session_limit_error_is_distinguishable():
    """A quota/auth failure must not be scored as a bad answer. The CLI writes
    some fatal messages to stdout with an empty stderr, so classification must
    look at both streams."""
    sys.path.insert(0, str(ROOT))
    from claude_bridge import ClaudeCLIError, SessionLimitError, _looks_like_limit, _cli_failure_text

    assert issubclass(SessionLimitError, ClaudeCLIError)
    for text in ["Not logged in · Please run /login", "rate limit exceeded",
                 "usage limit reached, resets at 3pm", "429 Too Many Requests"]:
        assert _looks_like_limit(text), text
    assert not _looks_like_limit("model produced invalid JSON")

    class R:
        stdout = "Not logged in · Please run /login"
        stderr = ""
    assert _cli_failure_text(R()) == "Not logged in · Please run /login"


def test_gate_tolerates_arm_labelled_envelope(tmp_path):
    """Adding arm metadata must not break the existing regression gate."""
    sys.path.insert(0, str(ROOT))
    from eval.gate import _load_results, _compute_metrics

    env = {
        "run_id": "r1", "subset": "all", "arm": "A", "arm_name": "A_hybrid_rag",
        "arm_config_hash": "abc123", "judge_runs": 3,
        "results": [{
            "id": "h01", "question_type": "qa", "holdout": False, "verdict": "EQUIVALENT",
            "recall": {"applicable": True, "source_full": True, "pages_full": True},
            "mrr_at_10": 1.0, "ndcg_at_10": 1.0, "arm": "A",
            "judge": {"relevance": 5, "groundedness": 5, "citation_accuracy": 5,
                      "critical_errors": ["NONE"]},
            "citation_validation": {"page_accuracy": 1.0, "n_citations": 2},
        }],
    }
    p = tmp_path / "res.json"
    p.write_text(json.dumps(env), encoding="utf-8")
    rows, meta = _load_results(p)
    assert len(rows) == 1 and meta["arm"] == "A"
    assert _compute_metrics(rows)["judge_median_relevance"] == 5


# ── Ablation Phase 2: arm B (full context) and arm C (agentic) ──────


def test_arm_b_context_is_complete_and_parseable():
    """Arm B must see the WHOLE corpus, and its headers must parse with the same
    citation parser arm A's do — otherwise arm B loses citation metrics for a
    formatting reason rather than a capability one."""
    sys.path.insert(0, str(ROOT))
    import re
    from citations import parse_citations
    from eval.arms import build_full_corpus_context
    from vectorstore import get_all_chunks

    ctx, chunks, meta = build_full_corpus_context("capstone")
    stored = get_all_chunks(project="capstone")

    assert meta["n_chunks"] == len(stored), "arm B must carry every chunk"
    assert meta["n_sources"] == len({c["source"] for c in stored})
    assert len(ctx) == meta["chars"]
    assert "COMPLETE set of source documents" in ctx

    # Every chunk header must be in the F10 parseable shape.
    headers = re.findall(r"\[([^\[\]]+), (page|pages) ([0-9,\- ]+)\]", ctx)
    assert len(headers) >= meta["n_chunks"], "one parseable header per chunk"
    src, label, pages = headers[0]
    parsed = parse_citations(f"Per [{src}, {label} {pages}] the answer is X.")
    assert parsed and parsed[0]["pages"], "arm B header must round-trip through parse_citations"

    # The old dump_corpus shape must NOT appear — it is unparseable.
    assert "[Pages [" not in ctx


def test_arm_b_config_hash_tracks_the_corpus():
    """The corpus IS arm B's configuration, so a re-ingest must invalidate its
    cached answers."""
    sys.path.insert(0, str(ROOT))
    from eval.arms import make_producer

    b1 = make_producer("B", project="capstone", top_k=10)
    b2 = make_producer("B", project="capstone", top_k=10)
    assert b1.config_hash() == b2.config_hash()
    assert b1.config_hash() != make_producer("A", project="capstone", top_k=10).config_hash()


def test_arm_b_does_not_claim_retrieval_metrics():
    """Arm B holds the whole corpus; reporting recall/MRR/nDCG would yield a
    meaningless but authoritative-looking 100%."""
    sys.path.insert(0, str(ROOT))
    import inspect
    from eval.arms import ArmBFullContext, ArmCAgenticFiles

    for cls in (ArmBFullContext, ArmCAgenticFiles):
        src = inspect.getsource(cls.produce)
        assert "retrieval_applicable=True" not in src, f"{cls.__name__} must not rank"


def test_agentic_sandbox_fails_closed(tmp_path):
    """eval/questions_hard.json holds every gold answer, so the agent must not be
    able to reach the repo — and a CLAUDE.md anywhere above the work dir would
    pull the rubric into context."""
    sys.path.insert(0, str(ROOT))
    from claude_bridge import assert_agentic_sandbox, AgenticSandboxError

    with pytest.raises(AgenticSandboxError):
        assert_agentic_sandbox(ROOT / "data", ROOT)          # inside the repo

    (tmp_path / "CLAUDE.md").write_text("rubric", encoding="utf-8")
    nested = tmp_path / "mirror"
    nested.mkdir()
    with pytest.raises(AgenticSandboxError):
        assert_agentic_sandbox(nested, ROOT)                 # CLAUDE.md in an ancestor

    with pytest.raises(AgenticSandboxError):
        assert_agentic_sandbox(tmp_path / "missing", ROOT)   # does not exist

    clean = tmp_path / "clean"
    clean.mkdir()
    (tmp_path / "CLAUDE.md").unlink()
    assert isinstance(assert_agentic_sandbox(clean, ROOT), list)


def test_agentic_envelope_parsing_is_defensive():
    """The CLI envelope shape is version-dependent and could not be verified from
    inside a Claude Code session, so the parser must never explode."""
    sys.path.insert(0, str(ROOT))
    from claude_bridge import _parse_agentic_stdout

    single = json.dumps({"type": "result", "result": "hello", "num_turns": 3})
    assert _parse_agentic_stdout(single, "json")["result"] == "hello"

    stream = "\n".join([
        json.dumps({"type": "assistant"}),
        json.dumps({"type": "result", "result": "first", "num_turns": 1}),
        json.dumps({"type": "result", "result": "final", "num_turns": 7}),
    ])
    last = _parse_agentic_stdout(stream, "stream-json")
    assert last["result"] == "final" and last["num_turns"] == 7

    assert _parse_agentic_stdout("", "json") == {}
    assert _parse_agentic_stdout("not json", "json")["_unparsed"] is True
    assert _parse_agentic_stdout("garbage\nlines", "stream-json") == {}


def test_critical_errors_use_majority_not_union(monkeypatch):
    """Scores are median-aggregated, so a single dissenting judge run cannot move
    them — but critical errors were UNIONed, so one dissenting run could brand an
    answer with a gate-blocking error. With a measured relevance flip-rate of
    ~0.16 that is not rare, and false positives grow with --judge-runs by
    construction: the baseline run produced 10 blocking violations, 4 flagged by
    exactly 1 of 3 runs on answers judged EQUIVALENT at relevance 4-5."""
    sys.path.insert(0, str(ROOT))
    import eval.run as R

    runs = [
        {"relevance": 5, "groundedness": 5, "citation_accuracy": 5,
         "critical_errors": ["HALLUCINATION"], "short_rationale": "a"},
        {"relevance": 5, "groundedness": 5, "citation_accuracy": 5,
         "critical_errors": ["NONE"], "short_rationale": "b"},
        {"relevance": 5, "groundedness": 5, "citation_accuracy": 5,
         "critical_errors": ["NONE"], "short_rationale": "c"},
    ]
    monkeypatch.setattr(R, "_judge_once", lambda *a, **k: runs.pop(0) if runs else None)
    out = R._judge_llm_aggregated("q", "ev", "exp", "cand", n_runs=3)
    assert out["critical_errors"] == ["NONE"], "1-of-3 must not survive aggregation"

    runs2 = [
        {"relevance": 4, "groundedness": 4, "citation_accuracy": 4,
         "critical_errors": ["CITATION_WRONG"], "short_rationale": "a"},
        {"relevance": 4, "groundedness": 4, "citation_accuracy": 4,
         "critical_errors": ["CITATION_WRONG"], "short_rationale": "b"},
        {"relevance": 4, "groundedness": 4, "citation_accuracy": 4,
         "critical_errors": ["NONE"], "short_rationale": "c"},
    ]
    monkeypatch.setattr(R, "_judge_once", lambda *a, **k: runs2.pop(0) if runs2 else None)
    out2 = R._judge_llm_aggregated("q", "ev", "exp", "cand", n_runs=3)
    assert out2["critical_errors"] == ["CITATION_WRONG"], "2-of-3 must survive"


def test_gate_blocks_new_critical_errors_but_not_carried_over():
    """A regression gate must distinguish 'this system has known issues' from
    'this change made it worse'. Absolute blocking made the gate permanently red
    once the baseline contained any critical error — useless as a signal."""
    sys.path.insert(0, str(ROOT))
    from eval.gate import _critical_error_violations, _critical_errors_carried_over

    def row(qid, errs, qtype="synthesis"):
        return {"id": qid, "question_type": qtype,
                "must_cite_sources": [{"source": "S", "pages": [1]}],
                "judge": {"critical_errors": errs}}

    baseline = [row("h01", ["HALLUCINATION"]), row("h02", ["NONE"])]
    same = [row("h01", ["HALLUCINATION"]), row("h02", ["NONE"])]
    worse = [row("h01", ["HALLUCINATION"]), row("h02", ["HALLUCINATION"])]

    assert _critical_error_violations(same, baseline) == [], "carried-over must not block"
    assert len(_critical_errors_carried_over(same, baseline)) == 1
    assert len(_critical_error_violations(worse, baseline)) == 1, "new error must block"

    # No baseline → the original absolute behaviour.
    assert len(_critical_error_violations(same, None)) == 1


def test_citation_parser_rejects_prose_false_positives():
    """Found by tools/probe_agentic.py on a real arm C answer.

    Two bugs made fluent prose parse as citations, which lands directly in the
    precision metric the ablation compares — and arms differ in how chatty they
    are, so the penalty was differentially unfair:

    1. The inline pattern allowed whitespace-only separation, so "the RevPASH
       section on page 5" parsed as source="RevPASH section on".
    2. A repeated citation was deduplicated WITHOUT claiming its span, letting a
       looser pattern match a fragment inside the second occurrence — the third
       "[5 KPIs … Manager Should Track, page 8]" yielded a phantom citation with
       source="Manager Should Track", which then passed validation by substring
       match and padded the citation count.
    """
    sys.path.insert(0, str(ROOT))
    from citations import parse_citations

    for prose in [
        "The RevPASH section on page 5 explains it.",
        "Table Turn Time is defined on page 8.",
        "Revenue grew, see page 12.",
    ]:
        assert parse_citations(prose) == [], prose

    # A citation repeated three times yields exactly one entry and no fragments.
    src = "5 KPIs Every Clever Café Manager Should Track"
    answer = " ".join([f"Some claim [{src}, page 8]."] * 3)
    got = parse_citations(answer)
    assert len(got) == 1, got
    assert got[0]["source"] == src and got[0]["pages"] == [8]

    # Every legitimate shape must still parse.
    shapes = [
        f"See [{src}, page 8].",
        f"See [{src}, pages 7-8].",
        f"See [{src}, pages [7, 8]].",
        f"See ({src}, page 8).",
        f"It is on page 8 of {src}.",
        f"{src}, pages 7-8 covers it.",
    ]
    for s in shapes:
        assert parse_citations(s), f"legitimate citation shape stopped parsing: {s}"


def test_cli_subprocess_uses_plan_auth_not_api_key(monkeypatch):
    """CLAUDE.md's contract is plan limits, not metered API billing — but the
    CLI's auth precedence puts ANTHROPIC_API_KEY ahead of subscription OAuth, so
    a key in the user environment silently redirects every call to a paid API.
    This machine has a real 108-char key in the user-scope environment."""
    sys.path.insert(0, str(ROOT))
    import inspect
    from claude_bridge import _plan_auth_env, call_claude, call_claude_agentic

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-FAKE")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok-fake")
    monkeypatch.delenv("PDFRAG_ALLOW_API_KEY", raising=False)

    env = _plan_auth_env()
    assert "ANTHROPIC_API_KEY" not in env
    assert "ANTHROPIC_AUTH_TOKEN" not in env
    assert "PATH" in env, "only credential vars may be removed"

    monkeypatch.setenv("PDFRAG_ALLOW_API_KEY", "1")
    assert "ANTHROPIC_API_KEY" in _plan_auth_env(), "escape hatch must work"

    # Both call paths must actually use it, not just define it.
    for fn in (call_claude, call_claude_agentic):
        assert "_plan_auth_env" in inspect.getsource(fn), fn.__name__


def test_agentic_setting_sources_uses_documented_syntax():
    """Valid values are user/project/local, comma-separated. An empty string is
    undocumented and is not something to build an experiment on."""
    sys.path.insert(0, str(ROOT))
    import inspect
    from claude_bridge import call_claude_agentic

    src = inspect.getsource(call_claude_agentic)
    assert '"--setting-sources", ""' not in src
    assert '"project,local"' in src


def test_agentic_tool_set_excludes_bash():
    """Bash would let the agent shell out to pdftotext (present on this machine)
    and grant itself an extraction capability arm A does not have."""
    sys.path.insert(0, str(ROOT))
    from claude_bridge import AGENTIC_TOOLS, AGENTIC_DENY

    assert set(AGENTIC_TOOLS) == {"Read", "Grep", "Glob"}
    for banned in ("Bash", "Write", "Edit", "WebFetch", "WebSearch"):
        assert banned in AGENTIC_DENY
        assert banned not in AGENTIC_TOOLS


def test_arm_c_shares_the_pinned_citation_format():
    """All three arms must request citations in the identical format, or the
    citation comparison measures prose style."""
    sys.path.insert(0, str(ROOT))
    from prompts import QA_SYSTEM
    from eval.arms import ARM_C_SYSTEM_SUFFIX, ARM_C_USER

    assert ARM_C_SYSTEM_SUFFIX.startswith(QA_SYSTEM), "arm C must reuse QA_SYSTEM verbatim"
    assert "=== PAGE N ===" in ARM_C_SYSTEM_SUFFIX
    # The shared tail must match arm A/B's QA_USER ending exactly.
    assert ARM_C_USER.strip().endswith("Answer (cite page numbers):")


def test_mirror_default_is_outside_repo_and_not_virtualized():
    """Two traps this guards against.

    1. ``%LOCALAPPDATA%`` is MSIX-redirected inside the Claude desktop app, so a
       mirror built there is invisible to a plain terminal — and arm C must run
       from a plain terminal to authenticate. Same path string, two physical
       directories, silently empty corpus.
    2. Containment must be component-aware: the mirror sibling ``pdf-rag-ablation``
       shares a string prefix with the repo ``pdf-rag``, so a naive ``startswith``
       check would wrongly call it "inside the repo".
    """
    sys.path.insert(0, str(ROOT))
    from tools.build_mirror import default_mirror_dir, is_redirected

    d = default_mirror_dir()
    assert not is_redirected(d), f"{d} is OS-redirected to {d.resolve()}"

    with pytest.raises(ValueError):
        d.resolve().relative_to(ROOT.resolve())      # i.e. genuinely outside


def test_mirror_slugs_are_ascii_and_unique():
    """Five of the 24 filenames carry NFD, emoji, ellipsis or smart quotes; an
    agent retyping them from a listing would silently miss files."""
    sys.path.insert(0, str(ROOT))
    from tools.build_mirror import slugify

    names = [
        "5 KPIs Every Clever Café Manager Should Track",
        "🤝 MIS 311 Team Accountability Checklist",
        "High-Level Strategic Roadmap - Transforming a Declining Coffee Shop…",
        "Student “How to Earn an A” One-Page Guide S26",
    ]
    slugs = [slugify(n) for n in names]
    for s in slugs:
        assert s and s.isascii() and " " not in s, s
    assert len(set(slugs)) == len(slugs)


def test_results_stem_keeps_every_run_shape_addressable():
    """Two runs landing on one filename is the cheapest way to lose a night of
    generations, and it has nearly happened twice: three arms sharing
    ``results_hard.json``, then a repeat seed sharing the first seed's file."""
    sys.path.insert(0, str(ROOT))
    from eval.run import results_stem

    # Arm A + own evidence + full run keeps the historical name, or eval/gate.py's
    # default --current path and the slow gate test below both break.
    assert results_stem(True, "A", "own", None) == "results_hard"

    stems = {
        results_stem(True, arm, ev, only, sfx)
        for arm in ("A", "B", "C")
        for ev in ("own", "corpus")
        for only in (None, "h01,h02")
        for sfx in ("", "seed2", "seed3")
    }
    assert len(stems) == 3 * 2 * 2 * 3, "two distinct run shapes share a filename"

    # A subset run must never be readable as a complete one.
    assert "_partial" in results_stem(True, "A", "corpus", "h01", "seed2")

    # The suffix reaches a filesystem path, so it must not traverse.
    traversed = results_stem(True, "A", "own", None, "../../etc/passwd")
    assert "/" not in traversed and "\\" not in traversed and ".." not in traversed


def test_judge_rubric_defines_every_label_and_states_chunk_granularity():
    """The rubric listed the critical-error vocabulary as a bare set with zero
    definitions, so HALLUCINATION became a bucket for 'went beyond the reference'
    and CITATION_WRONG for 'coarser than the reference's page numbers' — which the
    chunking makes unavoidable."""
    sys.path.insert(0, str(ROOT))
    import eval.run as R

    for label in R._VALID_ERRORS - {"NONE"}:
        assert label in R.JUDGE_USER, f"{label} is whitelisted but undefined in the rubric"
    # The judge must know a chunk spans several pages, or it scores citations
    # against the reference's page set instead of the evidence headers.
    assert "page RANGE" in R.JUDGE_USER
    assert "NOT a ceiling" in R.JUDGE_SYSTEM
    # Style preference must not sit in the same breath as unsupported-claim
    # penalties; judges were routing "too verbose" into the grounding axes.
    assert "verbosity" not in R.JUDGE_SYSTEM.lower()


def test_critical_error_vote_needs_a_quote_the_candidate_actually_contains(monkeypatch):
    """Two of the six carried-over errors were founded on text the answer never
    wrote — one run quoted figures that appear only in the *reference* answer, i.e.
    it graded the wrong document. Every one of the six sat at exactly 2-of-3, so
    dropping one unfounded vote is decisive."""
    sys.path.insert(0, str(ROOT))
    import eval.run as R

    candidate = ("The source works bottom-up from an Americano at $.77 sold at $2.75 "
                 "[Calculating Your Break Even Point, pages 4-5].")
    runs = [
        {"relevance": 5, "groundedness": 3, "citation_accuracy": 3,
         "critical_errors": ["HALLUCINATION"],
         "critical_error_quotes": [["HALLUCINATION", "the $7,200 fixed and $2,800 variable figures"]],
         "short_rationale": "a"},
        {"relevance": 5, "groundedness": 4, "citation_accuracy": 4,
         "critical_errors": ["HALLUCINATION"],
         "critical_error_quotes": [["HALLUCINATION", "an Americano at $.77 sold at $2.75"]],
         "short_rationale": "b"},
        {"relevance": 5, "groundedness": 5, "citation_accuracy": 5,
         "critical_errors": ["NONE"], "critical_error_quotes": [], "short_rationale": "c"},
    ]
    monkeypatch.setattr(R, "_judge_once", lambda *a, **k: runs.pop(0) if runs else None)
    out = R._judge_llm_aggregated("q", "ev", "exp", candidate, n_runs=3)
    # The fabricated vote is dropped, so 2-of-3 becomes 1-of-3 and the label clears.
    assert out["critical_errors"] == ["NONE"]

    # ...and a quote that IS present still counts.
    assert R._quote_is_in_candidate("an Americano at $.77", candidate) is True
    assert R._quote_is_in_candidate("figures found nowhere", candidate) is False
    # Whitespace-reflowed copies must still resolve, or real defects get dropped.
    assert R._quote_is_in_candidate("an   Americano\nat $.77", candidate) is True
    # Legacy rows carry no quote and must fail OPEN, or re-aggregating stored
    # per_run data would silently zero every existing critical error.
    assert R._quote_is_in_candidate("", candidate) is True


def test_judge_parser_accepts_both_error_shapes():
    sys.path.insert(0, str(ROOT))
    import eval.run as R

    new = R._parse_judge_json(
        '{"relevance":4,"groundedness":4,"citation_accuracy":4,'
        '"critical_errors":[{"label":"CITATION_WRONG","quote":"pages 24-25"}],'
        '"short_rationale":"r"}')
    assert new["critical_errors"] == ["CITATION_WRONG"]
    assert new["critical_error_quotes"] == [["CITATION_WRONG", "pages 24-25"]]

    legacy = R._parse_judge_json(
        '{"relevance":4,"groundedness":4,"citation_accuracy":4,'
        '"critical_errors":["CITATION_WRONG"],"short_rationale":"r"}')
    assert legacy["critical_errors"] == ["CITATION_WRONG"]
    assert legacy["critical_error_quotes"] == [["CITATION_WRONG", ""]]


def test_judge_rationale_survives_past_300_chars():
    """h07's stored rationale ended mid-word at 'and several oth' — the run was
    listing further objections and the record cut exactly where the list began."""
    sys.path.insert(0, str(ROOT))
    import eval.run as R

    long_r = ("the candidate asserts a figure absent from the evidence, " * 12).strip()
    out = R._parse_judge_json(json.dumps({
        "relevance": 4, "groundedness": 3, "citation_accuracy": 4,
        "critical_errors": ["HALLUCINATION"], "short_rationale": long_r}))
    assert len(out["short_rationale"]) > 600
    assert out["short_rationale"].startswith("the candidate asserts")


def test_results_envelope_carries_the_prompt_hashes():
    """Without these the gate compares two files scored under different rubrics
    and cannot tell — the same blindness that let a legacy baseline silently SKIP
    five of six tracked metrics."""
    sys.path.insert(0, str(ROOT))
    import inspect
    import eval.run as R

    src = inspect.getsource(R.run_eval)
    assert '"judge_prompt_hash": judge_prompt_hash' in src
    assert '"qa_prompt_hash": qa_prompt_hash' in src


# ── SDK-ready bridge ────────────────────────────────────────────────


def _fake_sdk(monkeypatch, capture, *, raise_exc=None):
    """Install a fake anthropic module + client. Never touches the network."""
    import types
    sys.path.insert(0, str(ROOT))
    import claude_bridge as B

    anthropic = types.ModuleType("anthropic")

    class APIError(Exception): pass
    class APIConnectionError(APIError): pass
    class AuthenticationError(APIError): pass
    class RateLimitError(APIError): pass
    anthropic.APIError = APIError
    anthropic.APIConnectionError = APIConnectionError
    anthropic.AuthenticationError = AuthenticationError
    anthropic.RateLimitError = RateLimitError

    class _Msg:
        stop_reason = "end_turn"
        content = [types.SimpleNamespace(type="text", text="  hi  ")]
        usage = types.SimpleNamespace(input_tokens=1, cache_read_input_tokens=44_085,
                                      cache_creation_input_tokens=0, output_tokens=7)

    class _Messages:
        def create(self, **kw):
            capture.update(kw)
            if raise_exc:
                raise raise_exc
            return _Msg()

        def count_tokens(self, **kw):
            capture.update(kw)
            return types.SimpleNamespace(input_tokens=1234)

    class _Client:
        messages = _Messages()
        def with_options(self, **kw):
            capture["_options"] = kw
            return self

    anthropic.Anthropic = lambda **kw: (capture.update({"_client_kwargs": kw}), _Client())[1]
    monkeypatch.setitem(sys.modules, "anthropic", anthropic)
    monkeypatch.setattr(B, "_SDK_CLIENT", None, raising=False)
    return B, anthropic


def test_sdk_backend_requires_double_opt_in(monkeypatch):
    """`_plan_auth_env()` strips ANTHROPIC_API_KEY because that is right for the
    CLI and fatal for the SDK. A single env var must never be able to flip the
    project onto metered billing."""
    sys.path.insert(0, str(ROOT))
    import claude_bridge as B, config

    monkeypatch.setattr(config, "BRIDGE_BACKEND", "sdk")
    monkeypatch.delenv("PDFRAG_ALLOW_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    with pytest.raises(B.ClaudeCLIError, match="PDFRAG_ALLOW_API_KEY"):
        B._assert_sdk_opt_in()

    monkeypatch.setenv("PDFRAG_ALLOW_API_KEY", "1")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(B.ClaudeCLIError, match="ANTHROPIC_API_KEY"):
        B._assert_sdk_opt_in()

    # ...and the guard is inert on the default backend.
    monkeypatch.setattr(config, "BRIDGE_BACKEND", "cli")
    B._assert_sdk_opt_in()


def test_sdk_maps_aliases_separates_system_and_drops_temperature(monkeypatch):
    """CLI aliases are not API model IDs. And `temperature` is REJECTED (400) by
    claude-opus-5 / claude-sonnet-5 — forwarding the project's verifier
    convention of temperature=0.0 would fail every judge call."""
    cap = {}
    B, _ = _fake_sdk(monkeypatch, cap)
    import config
    monkeypatch.setattr(config, "BRIDGE_BACKEND", "sdk")
    monkeypatch.setenv("PDFRAG_ALLOW_API_KEY", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

    out = B.call_claude(model="sonnet", system="SYS", user="USR", temperature=0.0)
    assert out == "hi"
    assert cap["model"] == "claude-sonnet-5", "alias was not mapped to an API model ID"
    assert cap["system"] == "SYS", "system must be its own kwarg, not concatenated"
    assert cap["messages"] == [{"role": "user", "content": "USR"}]
    assert "temperature" not in cap, "temperature would 400 on this model family"
    assert "top_p" not in cap and "top_k" not in cap


def test_sdk_envelope_feeds_total_input_tokens(monkeypatch):
    """`usage.input_tokens` alone reads 1 against a true 44,086 when cache-served."""
    cap = {}
    B, _ = _fake_sdk(monkeypatch, cap)
    import config
    monkeypatch.setattr(config, "BRIDGE_BACKEND", "sdk")
    monkeypatch.setenv("PDFRAG_ALLOW_API_KEY", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

    text, env = B.call_claude_json(model="opus", system="", user="U")
    assert text == "hi" and cap["model"] == "claude-opus-5"
    assert "system" not in cap, "empty system must be omitted, not sent as ''"
    assert B.total_input_tokens(env["usage"]) == 44_086


def test_sdk_rate_limit_maps_to_session_limit_error(monkeypatch):
    """Callers already branch on SessionLimitError to checkpoint and stop rather
    than score an outage as a wrong answer. That must hold on both backends."""
    cap = {}
    import types
    B, anthropic = _fake_sdk(monkeypatch, cap, raise_exc=None)
    import config
    monkeypatch.setattr(config, "BRIDGE_BACKEND", "sdk")
    monkeypatch.setenv("PDFRAG_ALLOW_API_KEY", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

    assert isinstance(B._map_sdk_error(anthropic.RateLimitError("429")), B.SessionLimitError)
    assert isinstance(B._map_sdk_error(anthropic.AuthenticationError("401")), B.SessionLimitError)
    other = B._map_sdk_error(anthropic.APIError("500"))
    assert isinstance(other, B.ClaudeCLIError) and not isinstance(other, B.SessionLimitError)


def test_default_backend_is_cli_and_agentic_never_dispatches():
    """The shipped contract is plan limits. Default must not change, and the
    agentic path drives Claude Code's own tool loop — no SDK equivalent."""
    sys.path.insert(0, str(ROOT))
    import inspect, config
    import claude_bridge as B

    assert config.BRIDGE_BACKEND == "cli"
    # Check the code, not the docstring — the docstring is *supposed* to mention it.
    src = inspect.getsource(B.call_claude_agentic)
    body = src.replace(B.call_claude_agentic.__doc__ or "", "")
    assert 'BRIDGE_BACKEND == "sdk"' not in body, "agentic path must stay CLI-only"
    assert "CLI-only" in (B.call_claude_agentic.__doc__ or "")
    # ...while both text entry points DO dispatch.
    for fn in (B.call_claude, B.call_claude_json):
        assert 'BRIDGE_BACKEND == "sdk"' in inspect.getsource(fn), fn.__name__


def test_no_hardcoded_model_aliases_outside_config():
    """A bare "opus"/"sonnet" would 404 in SDK mode — every call site maps
    through config.MODEL_IDS."""
    sys.path.insert(0, str(ROOT))
    import re
    for name in ("compose_capstone.py", "groundedness.py", "pipeline.py", "hyde.py"):
        src = (ROOT / name).read_text(encoding="utf-8")
        hits = re.findall(r'call_claude\w*\(\s*["\'](opus|sonnet|haiku)["\']', src)
        assert not hits, f"{name} hardcodes model alias(es): {hits}"


# ── Citation claim support ──────────────────────────────────────────
#
# `page_accuracy` asks "is this a real source and a page you were shown"; claim
# support asks "does that chunk contain this claim". These tests pin the second
# without an LLM: the adjudicator is an injected callable.

_CHUNK_1417 = (
    "## The Cost of Time\n\nAs coffee shop owners we spend our days putting out fires. "
    "Issues with customers, vendors and employees can eat up a large part of the day. "
    "Time is our most precious resource. When you run out of time or waste it you become "
    "grumpy, and ineffective at making good decisions. inefficient, Over time, this could "
    "cost you significant money and ruin your coffee business."
)
_CHUNK_1921 = (
    "## Summary\n\nWe've covered a lot of hidden costs that can wreak havoc on a coffee "
    "shop business. We summarize these potential business-threatening costs below:\n\n"
    "- Over-scheduling baristas\n- Avoidable coffee shop waste\n- Coffee shop inventory "
    "management\n- Employee giveaways\n- Marketing that isn't working\n- Lack of proper "
    "equipment maintenance\n- The cost of time\n"
)
_FIXTURE_CHUNKS = [
    {"id": "c1", "source": "7 Costs That Sink Coffee Shops", "pages": "[14, 15, 16, 17]",
     "text": _CHUNK_1417},
    {"id": "c2", "source": "7 Costs That Sink Coffee Shops", "pages": "[19, 20, 21]",
     "text": _CHUNK_1921},
    {"id": "c3", "source": "Loyalty Programs", "pages": "[11, 12, 13]",
     "text": "Digital loyalty programs tie rewards to customer order history."},
]


def test_no_rerank_skips_the_cross_encoder_and_keeps_rrf_order(monkeypatch):
    """The knob existed on `hybrid_search` but no caller could reach it, so its cost
    was never measurable. Skipping must actually skip: if the cross-encoder still
    loads, the latency saving this flag exists to measure is not real."""
    sys.path.insert(0, str(ROOT))
    import retrieval

    called = []
    monkeypatch.setattr(retrieval, "rerank",
                        lambda *a, **k: called.append(1) or [], raising=False)
    got = retrieval.hybrid_search("coffee shop break-even", top_k=5,
                                  project="capstone", use_rerank=False)
    assert not called, "cross-encoder was invoked despite use_rerank=False"
    assert got, "no-rerank path returned nothing"
    assert all(c.get("text") for c in got)
    # RRF order is what survives when rerank is off.
    scores = [c.get("rrf_score") for c in got if c.get("rrf_score") is not None]
    assert scores == sorted(scores, reverse=True), "results are not in RRF order"


def test_use_rerank_is_in_the_answer_cache_key():
    """The answer cache is content-addressed on the producer's config_hash. If
    use_rerank were absent, a --no-rerank eval would replay the reranked run's
    answers and the A/B would measure nothing while looking healthy."""
    sys.path.insert(0, str(ROOT))
    from eval.arms import make_producer

    on = make_producer("A", project="capstone", top_k=10, use_rerank=True)
    off = make_producer("A", project="capstone", top_k=10, use_rerank=False)
    assert on.config_hash() != off.config_hash()
    assert make_producer("A", project="capstone", top_k=10).config_hash() == on.config_hash(), \
        "default must stay identical, or every cached answer is invalidated"


def test_source_matching_folds_typographic_punctuation():
    """Extractors keep the curly apostrophe in a stored source name; a model retypes
    it in ASCII. Without folding, the citation resolves to NOTHING — measured on 15
    real citations across three arms, each silently scoring 0.0 support."""
    sys.path.insert(0, str(ROOT))
    from citations import _source_matches

    pairs = [
        ("Top Metrics to Track to Measure Your Coffee Shop Franchise's Performance",
         "Top Metrics to Track to Measure Your Coffee Shop Franchise’s Performance"),
        ('Student "How to Earn an A" One-Page Guide S26',
         "Student “How to Earn an A” One-Page Guide S26"),
        ("High-Level Strategic Roadmap - Transforming a Declining Coffee Shop...",
         "High-Level Strategic Roadmap - Transforming a Declining Coffee Shop…"),
    ]
    for cited, stored in pairs:
        assert _source_matches(cited, stored), f"{cited!r} should match {stored!r}"
        assert _source_matches(stored, cited), "matching must be symmetric"

    # ...and it must not collapse genuinely different sources.
    assert not _source_matches("7 Costs That Sink Coffee Shops", "5 KPIs Every Clever Café Manager")


def test_citation_occurrences_recover_spans_without_moving_the_denominator():
    """`n_citations` is the denominator of the GATE-TRACKED page_accuracy, so dedup
    must not change — but each occurrence attaches to a different claim."""
    sys.path.insert(0, str(ROOT))
    from citations import parse_citations, citation_occurrences, nfc_answer

    ans = ("Alpha [7 Costs That Sink Coffee Shops, pages 14-17]. Beta "
           "[7 Costs That Sink Coffee Shops, pages 14-17]. Gamma "
           "[7 Costs That Sink Coffee Shops, pages 14-17].")
    parsed = parse_citations(ans)
    assert len(parsed) == 1, "dedup changed: page_accuracy's denominator would move"
    assert len(parsed[0]["spans"]) == 3, "occurrences are not recoverable"

    occ = citation_occurrences(ans)
    assert len(occ) == 3
    na = nfc_answer(ans)
    for o in occ:
        s, e = o["span"]
        assert na[s:e] == o["raw"], "offsets must index the NFC-normalized answer"


def test_quote_verification_is_fuzzy_because_extraction_reorders_text():
    """Exact-substring fail-closed rejects CORRECT citations: the PDF backend
    physically reorders text, so a faithful quote is not a substring of its own
    source chunk. Measured on real data before this threshold was chosen."""
    sys.path.insert(0, str(ROOT))
    from citation_support import build_idf, verify_quote

    idf = build_idf(_FIXTURE_CHUNKS)
    q = "inefficient, grumpy, and ineffective at making good decisions"
    assert q.lower() not in _CHUNK_1417.lower(), "fixture must reproduce the scrambling"
    assert verify_quote(q, _CHUNK_1417, idf) == "fuzzy"
    # ...but a fabrication and a wrong-chunk quote are still rejected.
    assert verify_quote("RevPASH rose 42% in the third quarter", _CHUNK_1417, idf) == "none"
    assert verify_quote(q, _CHUNK_1921, idf) == "none"


def test_evidence_resolution_unions_adjacent_chunks_and_flags_fabricated_pages():
    """Adjacent chunks share a boundary page by construction, so an argmax would be
    decided by a tie-break — and a tie-break by list order picks the wrong chunk."""
    sys.path.insert(0, str(ROOT))
    from citation_support import resolve_evidence

    ev, ids, grade = resolve_evidence(
        {"source": "7 Costs That Sink Coffee Shops", "pages": [14, 15, 16, 17]},
        _FIXTURE_CHUNKS)
    assert grade == "EXACT" and ids == ["c1"] and _CHUNK_1417 in ev

    _, _, g = resolve_evidence(
        {"source": "7 Costs That Sink Coffee Shops", "pages": [88, 89, 90]}, _FIXTURE_CHUNKS)
    assert g == "UNRESOLVED_PAGES", "a fabricated page must short-circuit before any LLM call"

    _, _, g2 = resolve_evidence({"source": "No Such Doc", "pages": [1]}, _FIXTURE_CHUNKS)
    assert g2 == "UNRESOLVED_SOURCE"


def test_support_is_a_fraction_so_one_bad_part_does_not_zero_a_long_citation():
    """A conjunctive "every part supported" rule zeroes a correct citation whenever
    one part of a ten-part window is a false negative, and answers really do pack
    ten sub-claims under one marker."""
    sys.path.insert(0, str(ROOT))
    from citation_support import build_idf, score_citation_support

    idf = build_idf(_FIXTURE_CHUNKS)
    ans = ("Owners lose time to customers, vendors and employees, which makes them "
           "ineffective at decisions [7 Costs That Sink Coffee Shops, pages 14-17].")

    def stub(evidence, windows):
        parts = [{"text": f"p{i}", "verdict": "SUPPORTED", "quote": "our most precious resource"}
                 for i in range(9)]
        parts.append({"text": "p9", "verdict": "UNSUPPORTED", "quote": ""})
        return [{"index": i, "parts": parts} for i, _ in enumerate(windows)]

    r = score_citation_support(ans, _FIXTURE_CHUNKS, adjudicator=stub, idf=idf, runs=1)
    assert abs(r["claim_support_avg"] - 0.9) < 1e-9, r["claim_support_avg"]

    # The cap is a PROMPT instruction, never a slice: truncating the parts list
    # would drop this trailing UNSUPPORTED part and bias the score upward.
    def stub_tail_bad(evidence, windows):
        parts = [{"text": f"p{i}", "verdict": "SUPPORTED", "quote": "our most precious resource"}
                 for i in range(11)]
        parts.append({"text": "bad", "verdict": "UNSUPPORTED", "quote": ""})
        return [{"index": i, "parts": parts} for i, _ in enumerate(windows)]

    r2 = score_citation_support(ans, _FIXTURE_CHUNKS, adjudicator=stub_tail_bad, idf=idf, runs=1)
    assert r2["claim_support_avg"] < 1.0, "a trailing UNSUPPORTED part was silently dropped"


def test_supported_part_with_an_unverifiable_quote_is_demoted():
    """The one guarantee here that does not depend on the model's judgement."""
    sys.path.insert(0, str(ROOT))
    from citation_support import build_idf, score_citation_support

    idf = build_idf(_FIXTURE_CHUNKS)
    ans = "Owners lose time to vendors [7 Costs That Sink Coffee Shops, pages 14-17]."

    def stub(evidence, windows):
        return [{"index": i, "parts": [{"text": "x", "verdict": "SUPPORTED",
                                        "quote": "RevPASH rose 42% in the third quarter"}]}
                for i, _ in enumerate(windows)]

    r = score_citation_support(ans, _FIXTURE_CHUNKS, adjudicator=stub, idf=idf, runs=1)
    assert r["claim_support_avg"] == 0.0
    assert r["n_quote_rejected"] == 1


def test_abstain_contributes_to_neither_numerator_nor_denominator():
    """Folding an abstention in as 0.0 would be a lie about what was measured."""
    sys.path.insert(0, str(ROOT))
    from citation_support import build_idf, score_citation_support

    idf = build_idf(_FIXTURE_CHUNKS)

    def stub(evidence, windows):
        return [{"index": i, "parts": [{"text": "x", "verdict": "SUPPORTED",
                                        "quote": "our most precious resource"}]}
                for i, _ in enumerate(windows)]

    base = "Owners lose time to vendors [7 Costs That Sink Coffee Shops, pages 14-17]."
    # Long enough to escape the co-citation rule, but with no content tokens to judge.
    empty = " and the it is of to be in on at [Loyalty Programs, pages 11-13]."
    r1 = score_citation_support(base, _FIXTURE_CHUNKS, adjudicator=stub, idf=idf, runs=1)
    r2 = score_citation_support(base + empty, _FIXTURE_CHUNKS, adjudicator=stub, idf=idf, runs=1)
    assert r2["n_abstained"] >= 1, "a contentless window must ABSTAIN, not score 0.0"
    assert r1["claim_support_avg"] == r2["claim_support_avg"], "abstention moved the mean"


def test_back_to_back_citations_share_a_claim_and_union_their_evidence():
    """Answers write `…text [Doc A, page 3][Doc B, pages 1-3]`. The second marker's
    window is empty for a structural reason, so it inherits the claim — and it must
    also inherit the evidence, or it is asked about a claim its own chunk never
    carried alone and fails for a reason that is not a citation defect."""
    sys.path.insert(0, str(ROOT))
    from citation_support import attribute_claims, build_idf, score_citation_support

    idf = build_idf(_FIXTURE_CHUNKS)
    ans = ("Owners lose time and it is our most precious resource "
           "[7 Costs That Sink Coffee Shops, pages 14-17][Loyalty Programs, pages 11-13].")
    claims = attribute_claims(ans)
    assert claims[1]["co_cited_with"] == 0, "back-to-back marker did not co-cite"
    assert claims[1]["claim"] == claims[0]["claim"]

    def stub(evidence, windows):
        # Honest: SUPPORTED only when the quote really is in the evidence handed over.
        v = "SUPPORTED" if "precious resource" in evidence else "UNSUPPORTED"
        return [{"index": i, "parts": [{"text": "x", "verdict": v,
                                        "quote": "our most precious resource"}]}
                for i, _ in enumerate(windows)]

    r = score_citation_support(ans, _FIXTURE_CHUNKS, adjudicator=stub, idf=idf, runs=1)
    assert r["claim_support_avg"] == 1.0, "co-cited partner was not given the unioned evidence"


def test_gate_reports_claim_support_but_never_tracks_it():
    """It contains an LLM stage. A non-deterministic gate-tracked metric is exactly
    how the gate went permanently red before."""
    sys.path.insert(0, str(ROOT))
    import eval.gate as G

    assert "citation_claim_support_avg" not in G.DEFAULT_TOLERANCES
    assert "citation_claim_support_avg" not in G.ABSOLUTE_FLOORS
    m = G._compute_metrics(
        [{"citation_claim_support": {"claim_support_avg": 0.5}}],
        {"citation_support_runs": 3, "citation_support_scope": "own"})
    assert m["_citation_claim_support_avg"] == 0.5
    assert m["_citation_support_runs"] == 3


# ── Eval (slow, opt-in) ─────────────────────────────────────────────


@pytest.mark.slow
def test_eval_hard_passes_regression_gate():
    """Run the HARD eval (tuning subset for speed) and assert the regression
    gate passes against ``eval/baseline.json``.

    Why hard, not easy: the Weekend-3 gate inspects metrics (recall@10 pages,
    MRR, nDCG, judge medians, citation accuracy, critical errors) that the
    easy eval doesn't compute. Easy stays as a smoke regression alarm —
    re-add it as a separate slow test if you want both back.

    Why ``--holdout tuning``: we run on the 15 tuning questions during
    development. Holdout is reserved for "freeze and quote" runs (D1
    discipline rule)."""
    sys.path.insert(0, str(ROOT))
    from eval.gate import regression_gate  # noqa: E402

    result = subprocess.run(
        [sys.executable, str(ROOT / "eval" / "run.py"), "--hard", "--holdout", "tuning"],
        capture_output=True, text=True, encoding="utf-8", timeout=3600,
    )
    assert result.returncode == 0, f"hard eval failed:\n{result.stderr}\n{result.stdout[-1000:]}"
    out_json = ROOT / "eval" / "results_hard.json"
    assert out_json.exists(), "results_hard.json missing after run"

    exit_code = regression_gate(
        current_path=out_json,
        baseline_path=ROOT / "eval" / "baseline.json",
    )
    assert exit_code == 0, "regression gate failed; see stdout"
