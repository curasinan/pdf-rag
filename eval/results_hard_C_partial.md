# Eval Results — HARD

Run ID: `pilot1`
Subset: **all (tuning + holdout combined)**

==============================================================================
RESULTS — HARD eval  (3 questions, 127.6s)
==============================================================================
Retrieval recall@10 (source):    0.0%  (0/0)
Retrieval recall@10 (pages):     0.0%  (0/0)
Retrieval MRR@10:              n/a
Retrieval nDCG@10:             n/a
Answer correctness (EQUIVALENT):    66.7%  (2/3)
  + partial credit:                 66.7%  (+ 0 PARTIAL)
  different:                       1
  errors:                          0
──────────────────────────────────────────────────────────────────────────────
Judge median relevance:           4/5
Judge median groundedness:        1/5
Judge median citation_accuracy:   1/5
Judge mean flip-rate (relevance): 0.000
Citation page-accuracy (avg):     1.000
──────────────────────────────────────────────────────────────────────────────
Critical errors:                  CITATION_WRONG=1, HALLUCINATION=2, WRONG_EVIDENCE=1
==============================================================================

## Per-question

| ID | Type | recall src/pg | MRR | nDCG | rel/gnd/cit | cite-pg | Verdict | Question |
|---|---|---|---|---|---|---|---|---|
| h04 | page_lookup | — | — | — | 2/1/1 | 1.00 | DIFFERENT | Which page of the Calculating Your Break Even Point document contains the worked |
| h07 | synthesis | — | — | — | 4/1/1 | 1.00 | EQUIVALENT | Compare how the 'Briefing Doc - Opening and Operating a Profitable Coffee Shop'  |
| h12 | numeric | — | — | — | 5/5/5 | 1.00 | EQUIVALENT | What is the 2023 baseline annual revenue figure for Broadway Cafe in the financi |

## Failures (DIFFERENT, PARTIAL, ERROR, or critical error)

### h04 — DIFFERENT  (page_lookup)
**Q:** Which page of the Calculating Your Break Even Point document contains the worked example with concrete numbers?
**Required sources:** [{'source': 'Calculating Your Break Even Point', 'pages': [2, 3]}]
**Recall:** {'applicable': False, 'reason': 'C_agentic_files does not rank'}
**MRR@10:** None, **nDCG@10:** None
**Judge:** {'relevance': 2, 'groundedness': 1, 'citation_accuracy': 1, 'critical_errors': ['HALLUCINATION'], 'short_rationale': "The EVIDENCE block is empty, so none of the candidate's detailed page-by-page figures and citations can be verified as grounded, and its page-4-centric answer conflicts with the reference's pages 2-3.", 'flip_rate_relevance': 0.0, 'flip_rate_groundedness': 0.0, 'n_runs': 1, 'escalated': False, 'per_run': [{'relevance': 2, 'groundedness': 1, 'citation_accuracy': 1, 'critical_errors': ['HALLUCINATION'], 'short_rationale': "The EVIDENCE block is empty, so none of the candidate's detailed page-by-page figures and citations can be verified as grounded, and its page-4-centric answer conflicts with the reference's pages 2-3."}]}
**Citation validation:** {'n_citations': 3, 'n_source_valid': 3, 'n_page_valid': 3, 'source_accuracy': 1.0, 'page_accuracy': 1.0, 'per_citation': [{'source': 'Calculating Your Break Even Point', 'pages': [2], 'raw': '[Calculating Your Break Even Point, page 2]', 'source_exists': True, 'page_matches': True, 'valid': True}, {'source': 'Calculating Your Break Even Point', 'pages': [3], 'raw': '[Calculating Your Break Even Point, page 3]', 'source_exists': True, 'page_matches': True, 'valid': True}, {'source': 'Calculating Your Break Even Point', 'pages': [4], 'raw': '[Calculating Your Break Even Point, page 4]', 'source_exists': True, 'page_matches': True, 'valid': True}]}
**Retrieved:** []
**Expected:** Pages 2-3 contain the worked example: $7,200 monthly fixed costs (rent $2,000, insurance $300, loan $350, salary $4,200), $2,800 variable costs, $522 daily revenue.
**Got:** The worked example runs across **pages 2–4**, not a single page, and the calculation itself lands on **page 4**.

**How it breaks down:**

- **Page 2** introduces the sample scenario with startup cost estimates — Legal and Administrative $300, Coffee Equipment $12,000, Remodeling and Buildout $4,500, Furniture and Fixtures $2,500, Other Costs $2,500, for Initial Total Startup Costs of $21,800, plus a $10,000 loan at a $350 monthly payment [Calculating Your Break Even Point, page 2].

- **Page 3** supplies the operating numbers: fixed costs of Rent $2,000, Insurance $300, Loan & Interest $350, ...

### h07 — EQUIVALENT  (synthesis)
**Q:** Compare how the 'Briefing Doc - Opening and Operating a Profitable Coffee Shop' and 'Calculating Your Break Even Point' present the break-even calculation. What's the same and what's different?
**Required sources:** [{'source': 'Briefing Doc - Opening and Operating a Profitable Coffee Shop', 'pages': [4, 5]}, {'source': 'Calculating Your Break Even Point', 'pages': [2, 3, 4, 5]}]
**Recall:** {'applicable': False, 'reason': 'C_agentic_files does not rank'}
**MRR@10:** None, **nDCG@10:** None
**Judge:** {'relevance': 4, 'groundedness': 1, 'citation_accuracy': 1, 'critical_errors': ['CITATION_WRONG', 'HALLUCINATION', 'WRONG_EVIDENCE'], 'short_rationale': "The EVIDENCE block is empty, so none of the candidate's detailed page-level claims and citations can be verified as grounded, even though the content aligns with the reference answer.", 'flip_rate_relevance': 0.0, 'flip_rate_groundedness': 0.0, 'n_runs': 1, 'escalated': False, 'per_run': [{'relevance': 4, 'groundedness': 1, 'citation_accuracy': 1, 'critical_errors': ['HALLUCINATION', 'CITATION_WRONG', 'WRONG_EVIDENCE'], 'short_rationale': "The EVIDENCE block is empty, so none of the candidate's detailed page-level claims and citations can be verified as grounded, even though the content aligns with the reference answer."}]}
**Citation validation:** {'n_citations': 11, 'n_source_valid': 11, 'n_page_valid': 11, 'source_accuracy': 1.0, 'page_accuracy': 1.0, 'per_citation': [{'source': 'Briefing Doc - Opening and Operating a Profitable Coffee Shop', 'pages': [3], 'raw': '[Briefing Doc - Opening and Operating a Profitable Coffee Shop, page 3]', 'source_exists': True, 'page_matches': True, 'valid': True}, {'source': 'Calculating Your Break Even Point', 'pages': [1], 'raw': '[Calculating Your Break Even Point, page 1]', 'source_exists': True, 'page_matches': True, 'valid': True}, {'source': 'Briefing Doc', 'pages': [1], 'raw': '[Briefing Doc, page 1]', 'source_exists': True, 'page_matches': True, 'valid': True}, {'source': 'Briefing Doc, page 5 and page 7; Calculating Your Break Even Point', 'pages': [3], 'raw': '[Briefing Doc, page 5 and page 7; Calculating Your Break Even Point, page 3]', 'source_exists': True, 'page_matches': True, 'valid': True}, {'source': 'Calculating Your Break Even Point', 'pages': [5], 'raw': '[Calculating Your Break Even Point, page 5]', 'source_exists': True, 'page_matches': True, 'valid': True}, {'source': 'Briefing Doc, page 6; Calculating Your Break Even Point', 'pages': [5], 'raw': '[Briefing Doc, page 6; Calculating Your Break Even Point, page 5]', 'source_exists': True, 'page_matches': True, 'valid': True}, {'source': 'Briefing Doc', 'pages': [5], 'raw': '[Briefing Doc, page 5]', 'source_exists': True, 'page_matches': True, 'valid': True}, {'source': 'Calculating Your Break Even Point', 'pages': [2, 3], 'raw': '[Calculating Your Break Even Point, pages 2-3]', 'source_exists': True, 'page_matches': True, 'valid': True}, {'source': 'Calculating Your Break Even Point', 'pages': [2], 'raw': '[Calculating Your Break Even Point, page 2]', 'source_exists': True, 'page_matches': True, 'valid': True}, {'source': 'Calculating Your Break Even Point', 'pages': [4, 5], 'raw': '[Calculating Your Break Even Point, pages 4-5]', 'source_exists': True, 'page_matches': True, 'valid': True}, {'source': 'Briefing Doc', 'pages': [2], 'raw': '[Briefing Doc, page 2]', 'source_exists': True, 'page_matches': True, 'valid': True}]}
**Retrieved:** []
**Expected:** Both define break-even as the sales level where total costs are covered. The Briefing Doc gives a simple formula: Fixed Costs / Gross Margin %, with example $22,000 / 0.85 = $26,000. Calculating Your Break Even Point gives a more detailed multi-step method: amortize startup costs, sum monthly fixed and variable costs, then Fixed Costs / Sales Margin where Sales Margin = Gross Sales Revenue − Variable Costs. Worked example uses $7,200 fixed + $2,800 variable = $10,000 monthly cost vs ~$522/day revenue.
**Got:** Both documents cover the break-even point, but at very different levels of resolution.

## What's the same

**The conceptual definition is essentially identical — nearly verbatim.** The Briefing Doc's FAQ says your break-even point "is the moment in time where your total costs are equal to your revenue. Anything below your break-even point means you are not turning a profit. Anything above it constitutes a profit. When you reach your break-even point, the operations of your business have covered your fixed and variable costs" [Briefing Doc - Opening and Operating a Profitable Coffee Shop, page...
