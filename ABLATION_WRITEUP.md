# Is a RAG pipeline worth it for a corpus that fits in context?

An ablation of three architectures over the same 25-question evaluation set:
hybrid retrieval, whole-corpus prompting, and agentic file search.

---

## Summary

For a 24-document, 286K-character corpus, the hybrid RAG pipeline was **not**
worth its complexity. It was the slowest of the three architectures, cost more
per correct answer than agentic file search, and ranked last on every quality
measure — while the quality differences themselves were too small for this
design to distinguish from noise.

The honest one-line version: **quality was indistinguishable; cost and latency
were not, and retrieval lost on both.**

A follow-up second generation seed on the questions carrying the entire paired
signal left hybrid RAG last in every view and reproduced its gap to agentic
search exactly, while erasing the gap between agentic search and whole-corpus
prompting altogether.

The scope limit matters as much as the result. Whole-corpus prompting is only an
option *because* this corpus fits in a context window. Above roughly 200K tokens
that arm ceases to exist and the comparison becomes vacuous. This study says
nothing about corpora larger than the one tested.

---

## Setup

**Corpus.** 24 documents (PDF, DOCX, XLSX) on coffee-shop business operations —
286,008 characters of extracted text across 121 chunks, about 74K tokens.

**Evaluation set.** 25 questions across five types: `page_lookup` (6),
`synthesis` (5), `numeric` (5), `qa` (5), `negative` (4). Each carries an
expected answer, gold source pages, and type-appropriate assertions.

**Arms.**

| arm | architecture |
|---|---|
| **A** | Hybrid RAG: BGE-M3 dense + BM25 → reciprocal rank fusion → cross-encoder rerank → top-10 chunks as context |
| **B** | Whole corpus in one prompt: no retrieval, all 121 chunks as context |
| **C** | Agentic file search: Claude with `Read`/`Grep`/`Glob` over a plain-text mirror, no vector store, no embeddings |

**Held constant.** Same 25 questions, same generation model (Opus), same system
prompt and pinned citation format, same judge, same judge evidence. Arms A and B
render context through the *same* function, so they differ in chunk count and
nothing else. Arm C reads a text mirror produced by the same extraction the
pipeline ingests, so extraction quality is held constant by construction — a
build-time assertion confirms all 121 stored chunks appear in the mirror.

**Judging.** An evidence-only LLM judge scores relevance, groundedness and
citation accuracy on a 1-5 scale; numeric and negative questions use
deterministic rule-based judges. Three judge runs per question, median
aggregated. Evidence is **the entire corpus**, identical for every arm — see
[Methodology findings](#methodology-findings) for why that choice is load-bearing.

---

## Results: quality

| arm | EQUIVALENT | rel mean | groundedness (med) | citation precision | judge flip-rate |
|---|---|---|---|---|---|
| A — hybrid RAG | 23/25 (92%) | 4.68 | 5 | 0.96 | **0.167** |
| B — whole corpus | 24/25 (96%) | 4.80 | 5 | 0.96 | 0.094 |
| C — agentic files | **25/25 (100%)** | **4.96** | 5 | **0.98** | **0.031** |

**Citation-precision footnote (Aug 2026).** The three figures above are as measured
at the time of the study and are left unchanged. A later fix to source-name matching
— stored names carry typographic punctuation (`Franchise’s`, `“How to Earn an A”`)
that a model retypes in ASCII, and the normalizer folded neither — raised them to
**0.984 / 0.987 / 0.995**. The ordering is unchanged and no conclusion in this report
depends on it. Note also what this column does and does not mean: it is a
*fabrication* check ("a real source, and a page you were shown"), not an attribution
check. The attribution measure added afterwards scores the same answers
**0.923 / 0.906 / 0.871**, and arm C's is not comparable to the other two because it
validates against the whole corpus rather than a shown context.

### Paired comparisons

Every arm answers the same questions, so the comparison is paired — exact
McNemar on verdicts, Holm-corrected across the three pairs, plus a bootstrap over
resampled *question indices* applied identically to all arms.

| pair | discordant | McNemar p | Holm p | Δ pass rate | Δ relevance [95% CI] |
|---|---|---|---|---|---|
| A vs B | 1 | 1.000 | 1.000 | −4.0% | −0.12 [−0.32, +0.00] |
| A vs C | 2 | 0.500 | 1.000 | −8.0% | −0.28 [−0.60, −0.04] |
| B vs C | 1 | 1.000 | 1.000 | −4.0% | −0.16 [−0.44, +0.00] |

**Nothing is statistically separable.** At n=25 with α=0.05 and 80% power, the
smallest pass-rate gap this design can detect is **30 percentage points**. The
largest observed gap is 8. A null result here means *underpowered*, not
*equivalent* — this design cannot establish equivalence either.

One nuance reported rather than buried: the A-vs-C bootstrap on mean relevance
gives −0.28 with a CI of [−0.60, −0.04], which excludes zero. The binary test on
the same pair does not. With an upper bound of −0.04 against a judge that
disagrees with itself on 17% of adjacent runs for arm A, this is a directional
hint, not a finding.

### Per question type

| type | A | B | C |
|---|---|---|---|
| page_lookup | 4/6 | 5/6 | **6/6** |
| synthesis | 5/5 | 5/5 | 5/5 |
| numeric | 5/5 | 5/5 | 5/5 |
| qa | 5/5 | 5/5 | 5/5 |
| negative | 4/4 | 4/4 | 4/4 |

**Every failure in the entire study is a `page_lookup` question.** Four of the
five question types are saturated at 100% for all three architectures. Whatever
separates these arms, it is confined to the task of naming *where* a fact lives —
which is exactly where chunk granularity should be expected to hurt. (Per-type
counts of 4-6 questions have no statistical power; this is a description, not a
test.)

---

## Results: cost and latency

| arm | wall s/question | p90 | input tokens/q | output tokens/q | total $ | **$ per correct answer** |
|---|---|---|---|---|---|---|
| A — hybrid RAG | **57.6** | 66.8 | 41,172 | 873 | 5.26 | 0.229 |
| B — whole corpus | **19.1** | 34.6 | **132,358** | 940 | **29.69** | 1.237 |
| C — agentic files | 27.4 | 37.4 | 33,346 | 1,502 | 3.85 | **0.154** |

Two inversions carry the study:

**1. The retrieval pipeline is the slowest architecture.** Arm A takes 3× arm B's
wall clock. Retrieval — chiefly the CPU cross-encoder — accounts for 33-56s of
every query, against generation times comparable across all three arms. The
component whose entire purpose is to make generation cheap is the bottleneck.

**2. Arm A is dominated.** It is slower than both alternatives, costs 49% more
per correct answer than agentic search, and ranks last on every quality measure.
There is no axis measured here on which it wins. Whole-corpus prompting buys its
near-perfect score with 3.2× the input tokens and 5.6× the total cost; agentic
search is the cheapest per correct answer *and* faster than retrieval.

Input tokens are `input + cache_read + cache_creation`. The raw `input_tokens`
field reads near-zero when a prompt is cache-served — for arm A it reported **1**
against a true total of **44,086** — so a cost column built on it would have been
wrong by four orders of magnitude.

---

## Why hybrid RAG lost its two questions

Both failures are architectural, not tuning defects. Both survived a prior round
of retrieval fixes.

**h01 — retrieval never surfaced the answer.** The question asks what KPI #5 is
and where it is defined; the answer is on page 8. The top-10 contained chunks
`[1,2,3]` and `[4,5,6]` of the correct document plus five unrelated documents.
`pages_full=False`, `MRR=0.0`. The relevant chunk was never retrieved, so no
amount of generation quality could recover it. Arms B and C both answered
correctly, because neither has a retrieval step that can miss.

**h06 — retrieval succeeded; chunking destroyed the citation.** Here retrieval
was perfect (`MRR=1.0`, `pages_full=True`), but the answer could only cite
`pages 1-3` — the merged chunk — where the question asked for page 2.

This is the cleanest mechanistic result in the study, because **arm B hit the
same wall in the same way**, and its answer says so explicitly:

> "The sentence … appears in the article's opening section, which **the context
> labels as [5 KPIs Every Clever Café Manager Should Track, pages 1-3]**."

Arms A and B consume chunk-shaped context, so neither can cite more precisely
than a chunk boundary; both hedged across pages 1-3 rather than naming page 2.
Arm C — the only arm reading page-level text — answered it, and was the only arm
to score 6/6 on `page_lookup`.

So the one question type that separates these architectures separates them along
exactly the axis the architectures differ on: the granularity of the unit they
retrieve. That is not statistically significant at n=25. It is mechanistically
explicable and reproducible from the traces.

**A caveat the second seed forced, and it cuts both ways.** Re-running h06
produced, for arm B, an answer that states the same limitation in the same terms
("the context supplies page ranges per section rather than exact page numbers,
so I can narrow it to the pages 1-3 section but not to a single page") — so the
*mechanism* replicated verbatim. But the judge scored that answer **EQUIVALENT
(relevance 4)** where it had scored the first one **DIFFERENT (relevance 2)**,
apparently rewarding the second for explaining the limitation rather than
hedging about it. The chunk-granularity ceiling is real and reproducible; whether
an answer that hits it gets *counted* as a failure is close to a coin flip. Read
h06 as a mechanism, not as a tally.

---

## Methodology findings

These were more interesting than the headline result, and more transferable.

### The judge evidence policy moved the metric more than the architecture did

The evidence-only judge scores an answer against a supplied evidence block. What
goes in that block turned out to dominate the outcome. Scoring the *same cached
arm C answers* three ways:

| evidence given to the judge | EQUIVALENT | groundedness | critical errors |
|---|---|---|---|
| the arm's own context | 2/3 | **1** | HALLUCINATION ×2, +2 others |
| the question's gold passages | **1/3** | 2 | HALLUCINATION ×2, +2 others |
| the whole corpus | 2/3 | **4** | 1 |

*(measured during the 3-question pilot)*

- **Own context** hands an agentic arm an *empty* block — it has no "shown
  context" — so the judge correctly reports nothing is verifiable and returns
  groundedness 1. A pure harness artifact that would have read as "agentic search
  hallucinates badly."
- **Gold passages** penalise any arm that reads *beyond the label*. On one
  synthesis question the judge flagged arm C for inventing a break-even formula
  cited to page 1 of a document whose gold set listed only pages 4-5. Checking
  the PDF: page 1 does contain that formula. **The answer was right and the label
  was incomplete.** Since arms B and C see the whole corpus, they hit this
  systematically — unfixed, it would have biased the entire study toward
  retrieval.
- **The whole corpus** is label-independent, byte-identical across arms, and is
  the actual ground truth. It is the only defensible choice, and it is what the
  final numbers use.

### The judge's noise exceeds the gap between architectures

Running the identical cached answers through 1 judge run versus 3 **reversed the
ranking**: at one run, whole-corpus led 25/25 to agentic's 24/25; at three runs,
agentic led 25/25 to whole-corpus's 24/25. No answer changed — every generation
was replayed from cache. The flip is pure judge sampling.

Measured flip rates (share of adjacent judge runs disagreeing on relevance):
0.167 for arm A, 0.094 for B, 0.031 for C. When the judge disagrees with itself
on one in six comparisons, an 8-point pass-rate gap across 25 questions is not a
measurement.

### A second generation seed: the A-vs-C gap replicated, the B-vs-C gap did not

Every arm ran once per question, so each quality number was a single draw from a
stochastic generator. That is repairable cheaply, because the paired signal is
tiny and locatable: **21 of the 25 questions scored 5/5/5 across all three arms**
and contribute exactly zero to every paired delta. The reported A-vs-C delta of
-0.28 is precisely (3-5) + (4-5) + (4-5) + (2-5) over h01/h02/h05/h06, ÷ 25.
Re-rolling four questions re-rolls the entire quality conclusion.

Reseeding *only* those four would have been a trap — they were selected for being
extreme, so regression to the mean shrinks the gap whether or not the effect is
real. The second seed therefore covers the whole `page_lookup` stratum: the four
discordant questions plus h03 and h04, which were concordant and serve as
same-type controls.

| view | A | B | C | A vs C Δrel [95% CI] | B vs C discordant pairs |
|---|---|---|---|---|---|
| seed 1 | 23/25 | 24/25 | 25/25 | -0.28 [-0.60, -0.04] | 1 |
| seed 2 | 23/25 | **25/25** | 25/25 | -0.28 [-0.68, +0.00] | **0** |
| pooled | 23/25 | 24/25 | 25/25 | -0.28 [-0.60, -0.02] | 1 |

Three findings:

1. **Arm A vs arm C reproduced exactly** — the same -0.28 in both seeds and
   pooled, with the pooled interval still excluding zero. One measurement
   repeated is not significance, but it is no longer a single draw.
2. **Arm B vs arm C collapsed to nothing.** Seed 2 has *zero* discordant pairs
   between them; arm B scored 25/25. Whatever separated whole-corpus from agentic
   search in seed 1 did not survive one rerun.
3. **The drift is concentrated exactly where the signal is.** Both control
   questions were perfectly stable for all three arms — 0 flips in 6 cells — while
   the discordant stratum flipped a verdict in 25% of cells. The questions that
   distinguish the architectures are also the only unstable ones.

Per-arm verdict flips were 2/6 for arm A, 1/6 for arm B, 0/6 for arm C. Those are
six-cell estimates and the exact binomial intervals are correspondingly useless
(arm C's clean 0/6 still admits a true rate up to 0.46), so the ordering is
suggestive at best — but it points the same way as the judge flip rates.

One diagnostic worth more than the statistics: **arm A retrieved the byte-identical
chunk set in both seeds on all six questions**, MRR@10 unchanged throughout. None
of arm A's instability is retrieval instability — given the same chunks it writes
a differently-worded answer and the score follows the wording. The corollary is
the useful half: h01's retrieval miss (MRR 0.0 in both seeds) is fully
reproducible, so that failure is a property of the pipeline, not a bad draw.

### The ground truth had defects that favoured the incumbent

Gold page labels in this eval set were **chunk-shaped, not fact-shaped** — they
recorded where the retrieval pipeline *found* an answer, not where the fact
actually appears. That is invisible to the arm whose chunks span several pages,
and it penalises any arm that cites the precise page.

Five labels were corrected before the final run, each verified against the source
document: a cost total printed on a page the label omitted, a formula the label
placed on the wrong page, a spreadsheet's most direct source sheet missing
entirely. A mechanical audit script now checks every label against the sources.

### Measurement bugs found by pre-flight checks

Four checks run before any arm-C number was trusted (CLI envelope shape, sandbox
integrity, memory leakage, citation parseability). They failed usefully:

- **A billing trap.** A real API key in the user environment took precedence over
  subscription auth, so every call would have been metered API billing rather
  than plan usage — silently, and at three-arm scale.
- **Two citation-parser bugs.** A repeated citation was deduplicated without
  claiming its text span, letting a looser pattern match a fragment inside it and
  emit a phantom citation; and a pattern permitting whitespace-only separation
  turned ordinary prose ("the RevPASH section on page 5") into a citation. Both
  would have corrupted citation precision *differentially*, since the arms differ
  in how much prose they write.
- **An encoding gap.** Prose citations to sources with accented characters never
  parsed at all — the character classes were ASCII-only, so a document with `é`
  in its title was silently uncitable.

None of these would have announced themselves. They would have appeared as
plausible numbers in a comparison table.

---

## Threats to validity

- **n=25, MDE 30pp.** Only very large quality effects are detectable. Equivalence
  cannot be established.
- **One generation run per arm on 19 of 25 questions.** All confidence intervals
  are over *questions*, not reruns. The six `page_lookup` questions — which
  include all four that carry paired signal — were rerun once (see the second-seed
  section); the other nineteen were not, and they were all-arms-identical in the
  single run there is. A second seed on those could in principle open new
  discordance, though the two reseeded controls showed none.
- **Two seeds is still few.** Per-arm flip rates rest on six cells each; the
  exact binomial intervals span most of the unit interval. Seed 2 answers the
  question "does the headline gap survive one rerun" (A vs C yes, B vs C no) and
  nothing finer.
- **Self-judging.** The judge is the same model family as the generator, and the
  escalation judge is the same model. Same-family bias is unquantified here.
- **Corpus fits in context.** Arm B exists only under that condition. The result
  does not generalise past ~200K tokens.
- **Single domain, English prose, one corpus.** No claim beyond it.
- **Residual label imprecision.** Five labels were corrected; the remainder were
  screened mechanically but not exhaustively re-derived.
- **Arms are not perfectly matched.** Arm C's system prompt necessarily includes
  the agent harness's own scaffolding; arm B's prompt carries a "this is the
  complete corpus" preamble (without which negative questions are unanswerable);
  arm C gets an index file listing available documents. Each is disclosed rather
  than claimed away.
- **Critical-error counts are unioned across judge runs**, so they grow with the
  run count by construction and are comparable only within a single pass.

---

## Conclusion

For this corpus, retrieval earned its complexity on no measured axis. It was the
slowest architecture, the most expensive per correct answer after agentic search,
and last on every quality measure — and its two failures were structural
(a retrieval miss, and a citation that chunk boundaries made impossible) rather
than tuning defects.

The quality differences are not statistically separable, and this design could
not have detected them if they were real at this magnitude. A second generation
seed sharpened that picture without overturning it: hybrid RAG stayed last in
every view and its gap to agentic search reproduced to the decimal, but the gap
between agentic search and whole-corpus prompting vanished on the rerun. What
*is* measured precisely is cost and latency, and there the ordering is
unambiguous.

The broader lesson is less about RAG than about evaluation. The judge's evidence
policy, the judge's run count, and defects in the ground-truth labels each moved
the headline metric more than the architectural difference did. Three of those
four confounds favoured the incumbent architecture. A version of this study that
skipped the pilot would have produced a confident, well-evidenced, and wrong
conclusion.

---

## Reproduction

```bash
python tools/build_mirror.py                 # arm C corpus mirror (outside the repo)
python tools/probe_agentic.py                # 4 pre-flight checks; run from a plain terminal
python eval/run.py --hard --arm A --judge-runs 3 --judge-evidence corpus --run-id full1
python eval/run.py --hard --arm B --judge-runs 3 --judge-evidence corpus --run-id full1
python eval/run.py --hard --arm C --judge-runs 3 --judge-evidence corpus --run-id full1
python eval/ablation_report.py --suffix _corpus
```

Second generation seed — the `page_lookup` stratum, into a *separate* answer cache
so the first seed's cached answers cannot be replayed as if they were a new draw:

```bash
for ARM in A B C; do
  python eval/run.py --hard --arm $ARM --only h01,h02,h03,h04,h05,h06 \
    --judge-runs 3 --judge-evidence corpus \
    --cache-dir data/answer_cache_seed2 --run-id seed2 --out-suffix seed2
done
python eval/seed_stability.py --suffix seed2
```

Generated answers are content-addressed and cached, so re-judging or changing a
metric costs no generation. Runs checkpoint per question and resume with
`--resume`.

**Artifacts.** `eval/ablation_report_corpus.md` (tables),
`ablation_results_corpus.json` (machine-readable, includes per-question verdicts
and the bootstrap seed), `*_corpus_jr1.*` (the single-judge-run pass, retained for
the ranking-flip comparison), `data/traces/full1/` (per-question retrieval and
citation traces), `eval/seed_stability_seed2.md` / `.json` (second-seed drift,
recomputed paired statistics under all three views).
