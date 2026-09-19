# Eval Results — HARD

Run ID: `seed2`
Subset: **all (tuning + holdout combined)**

==============================================================================
RESULTS — HARD eval  (6 questions, 286.0s)
==============================================================================
Retrieval recall@10 (source):      n/a  (0/0)
Retrieval recall@10 (pages):       n/a  (0/0)
Retrieval MRR@10:              n/a
Retrieval nDCG@10:             n/a
Answer correctness (EQUIVALENT):   100.0%  (6/6)
  + partial credit:                100.0%  (+ 0 PARTIAL)
  different:                       0
  errors:                          0
──────────────────────────────────────────────────────────────────────────────
Judge median relevance:           5.0/5
Judge median groundedness:        5.0/5
Judge median citation_accuracy:   4.5/5
Judge mean flip-rate (relevance): 0.083
Citation page-accuracy (avg):     1.000
──────────────────────────────────────────────────────────────────────────────
Critical errors:                  CITATION_WRONG=1
==============================================================================

## Per-question

| ID | Type | recall src/pg | MRR | nDCG | rel/gnd/cit | cite-pg | Verdict | Question |
|---|---|---|---|---|---|---|---|---|
| h01 | page_lookup | — | — | — | 5/5/5 | 1.00 | EQUIVALENT | What is described as KPI #5 in the 5 KPIs document, and on which page is it defi |
| h02 | page_lookup | — | — | — | 5/5/5 | 1.00 | EQUIVALENT | On what pages does the Why Do Coffee Shops Fail document discuss owner burnout? |
| h03 | page_lookup | — | — | — | 5/5/4 | 1.00 | EQUIVALENT | On which pages of '7 Costs That Sink Coffee Shops' is 'Employee Giveaways' cover |
| h04 | page_lookup | — | — | — | 4/5/5 | 1.00 | EQUIVALENT | Which page of the Calculating Your Break Even Point document contains the worked |
| h05 | page_lookup | — | — | — | 5/4/4 | 1.00 | EQUIVALENT | Which pages of '5 KPIs' explain RevPASH and how it is calculated? |
| h06 | page_lookup | — | — | — | 5/5/3 | 1.00 | EQUIVALENT | On what page does '5 KPIs' first explicitly list 'Here are 5 KPIs every Clever C |

## Failures (DIFFERENT, PARTIAL, ERROR, or critical error)

### h06 — EQUIVALENT  (page_lookup)
**Q:** On what page does '5 KPIs' first explicitly list 'Here are 5 KPIs every Clever Café manager should track'?
**Required sources:** [{'source': '5 KPIs Every Clever Café Manager Should Track', 'pages': [2]}]
**Recall:** {'applicable': False, 'reason': 'C_agentic_files does not rank'}
**MRR@10:** None, **nDCG@10:** None
**Judge:** {'relevance': 5, 'groundedness': 5, 'citation_accuracy': 3, 'critical_errors': ['CITATION_WRONG'], 'short_rationale': "The evidence block's chunk headers only give page ranges (e.g. 'pages 1-3'), so there is no basis in the retrieved evidence to isolate the sentence to page 2 specifically as opposed to elsewhere in that same 1-3 range, making the precise page-2 citation unverifiable against the shown evidence even t", 'flip_rate_relevance': 0.0, 'flip_rate_groundedness': 0.0, 'n_runs': 3, 'escalated': False, 'per_run': [{'relevance': 5, 'groundedness': 5, 'citation_accuracy': 3, 'critical_errors': ['CITATION_WRONG'], 'short_rationale': "The evidence block's chunk headers only give page ranges (e.g. 'pages 1-3'), so there is no basis in the retrieved evidence to isolate the sentence to page 2 specifically as opposed to elsewhere in that same 1-3 range, making the precise page-2 citation unverifiable against the shown evidence even t"}, {'relevance': 5, 'groundedness': 5, 'citation_accuracy': 2, 'critical_errors': ['CITATION_WRONG'], 'short_rationale': "The evidence explicitly labels this document's chunk as 'pages 1-3', so the exact sentence falls within that page-1-3 span rather than being independently verifiable as page 2 alone — the reference answer and candidate both assert a specific page number (2) that isn't distinctly attributable given t"}, {'relevance': 5, 'groundedness': 5, 'citation_accuracy': 4, 'critical_errors': ['NONE'], 'short_rationale': "The candidate correctly answers page 2 per the retrieved chunk labeling (pages 1-3), matching the reference, though the page-2 attribution relies on inferring a subdivision within the labeled 'pages 1-3' chunk rather than an explicit standalone page-2 citation in evidence."}]}
**Citation validation:** {'n_citations': 2, 'n_source_valid': 2, 'n_page_valid': 2, 'source_accuracy': 1.0, 'page_accuracy': 1.0, 'per_citation': [{'source': '5 KPIs Every Clever Café Manager Should Track', 'pages': [2], 'raw': '[5 KPIs Every Clever Café Manager Should Track, page 2]', 'source_exists': True, 'page_matches': True, 'valid': True}, {'source': '5 KPIs Every Clever Café Manager Should Track', 'pages': [1], 'raw': '[5 KPIs Every Clever Café Manager Should Track, page 1]', 'source_exists': True, 'page_matches': True, 'valid': True}]}
**Retrieved:** []
**Expected:** The explicit '5 KPIs' framing appears on page 2 of the document, immediately followed by KPI #1 Employee Retention Rate.
**Got:** **Page 2.**

The sentence "Here are 5 KPIs every Clever Café manager should track:" appears on page 2, immediately after the paragraph introducing the five pillars and just before the first KPI heading, "1. Employee Retention Rate" [5 KPIs Every Clever Café Manager Should Track, page 2].

Page 1 contains a similar but differently worded line — "Here are 5 key KPIs that the savviest managers are following to ensure success!" — which is not the exact phrase asked about [5 KPIs Every Clever Café Manager Should Track, page 1].
