# Ablation: hybrid RAG vs whole-corpus prompting vs agentic file search

- Questions: **25** (paired across all arms)
- Judge evidence: **corpus**, judge runs: 3
- Generation model: `A_hybrid_rag` family, same for every arm

## Quality

| arm | EQUIV | rate | rel mean | rel med | gnd med | cite prec | med n_cit | % zero-cit |
|---|---|---|---|---|---|---|---|---|
| A — hybrid RAG | 23/25 | 92% | 4.68 | 5 | 5 | 0.96 | 3 | 0% |
| B — whole corpus | 24/25 | 96% | 4.80 | 5 | 5 | 0.96 | 3 | 0% |
| C — agentic files | 25/25 | 100% | 4.96 | 5 | 5 | 0.98 | 4 | 0% |

## Judge stability

| arm | LLM-judged Qs | mean flip-rate (relevance) | judge outages |
|---|---|---|---|
| A — hybrid RAG | 15 | 0.167 | none |
| B — whole corpus | 16 | 0.094 | none |
| C — agentic files | 16 | 0.031 | none |

The flip rate is the judge's own noise floor: the share of adjacent run pairs whose relevance score disagreed. **No arm gap smaller than this should be interpreted.** A judge outage is a question where the judge returned nothing despite the arm producing an answer — it is a harness failure, not a quality miss, and must not be scored as one.

## Cost and latency

| arm | wall s/q (mean) | wall s/q (p90) | input tok/q | output tok/q | $ total | $ per correct |
|---|---|---|---|---|---|---|
| A — hybrid RAG | 57.6 | 66.8 | 41,172 | 873 | 5.26 | 0.229 |
| B — whole corpus | 19.1 | 34.6 | 132,358 | 940 | 29.69 | 1.237 |
| C — agentic files | 27.4 | 37.4 | 33,346 | 1,502 | 3.85 | 0.154 |

Input tokens are `input + cache_read + cache_creation`. The raw `input_tokens` field alone reads near-zero when a prompt is served from cache and would under-report by orders of magnitude.

## Critical errors

| arm | CITATION_WRONG | FORMAT_FAIL | HALLUCINATION |
|---|---|---|---|
| A | 5 | 1 | 1 |
| B | 7 | 0 | 1 |
| C | 7 | 0 | 2 |

## Paired comparisons

| pair | b | c | discordant | McNemar p | Holm p | Δ pass rate | Δ relevance [95% CI] |
|---|---|---|---|---|---|---|---|
| A vs B | 0 | 1 | 1 | 1.000 | 1.000 | -4.0% | -0.12 [-0.32, +0.00] |
| A vs C | 0 | 2 | 2 | 0.500 | 1.000 | -8.0% | -0.28 [-0.60, -0.04] |
| B vs C | 0 | 1 | 1 | 1.000 | 1.000 | -4.0% | -0.16 [-0.44, +0.00] |

`b` = questions the first arm passed and the second failed; `c` = the reverse. Only discordant pairs carry information in a paired test.

## How much could this study detect?

At n=25, α=0.05, 80% power and an assumed 30% discordance rate, the smallest pass-rate gap detectable is **30%**.

> Any observed gap smaller than that is consistent with noise. This design can rule *in* large effects; it cannot establish equivalence. The cost and latency columns are measured far more precisely than the quality columns and are where the defensible conclusions live.

## Per-question verdicts

| qid | type | A | B | C |
|---|---|---|---|---|
| h01 | page_lookup | PARTIAL | EQUIVALENT | EQUIVALENT |
| h02 | page_lookup | EQUIVALENT | EQUIVALENT | EQUIVALENT |
| h03 | page_lookup | EQUIVALENT | EQUIVALENT | EQUIVALENT |
| h04 | page_lookup | EQUIVALENT | EQUIVALENT | EQUIVALENT |
| h05 | page_lookup | EQUIVALENT | EQUIVALENT | EQUIVALENT |
| h06 | page_lookup | DIFFERENT | DIFFERENT | EQUIVALENT |
| h07 | synthesis | EQUIVALENT | EQUIVALENT | EQUIVALENT |
| h08 | synthesis | EQUIVALENT | EQUIVALENT | EQUIVALENT |
| h09 | synthesis | EQUIVALENT | EQUIVALENT | EQUIVALENT |
| h10 | synthesis | EQUIVALENT | EQUIVALENT | EQUIVALENT |
| h11 | synthesis | EQUIVALENT | EQUIVALENT | EQUIVALENT |
| h12 | numeric | EQUIVALENT | EQUIVALENT | EQUIVALENT |
| h13 | numeric | EQUIVALENT | EQUIVALENT | EQUIVALENT |
| h14 | numeric | EQUIVALENT | EQUIVALENT | EQUIVALENT |
| h15 | numeric | EQUIVALENT | EQUIVALENT | EQUIVALENT |
| h16 | numeric | EQUIVALENT | EQUIVALENT | EQUIVALENT |
| h17 | qa | EQUIVALENT | EQUIVALENT | EQUIVALENT |
| h18 | qa | EQUIVALENT | EQUIVALENT | EQUIVALENT |
| h19 | qa | EQUIVALENT | EQUIVALENT | EQUIVALENT |
| h20 | qa | EQUIVALENT | EQUIVALENT | EQUIVALENT |
| h21 | qa | EQUIVALENT | EQUIVALENT | EQUIVALENT |
| h22 | negative | EQUIVALENT | EQUIVALENT | EQUIVALENT |
| h23 | negative | EQUIVALENT | EQUIVALENT | EQUIVALENT |
| h24 | negative | EQUIVALENT | EQUIVALENT | EQUIVALENT |
| h25 | negative | EQUIVALENT | EQUIVALENT | EQUIVALENT |
