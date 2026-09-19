# Eval Results — HARD

Run ID: `verify1`
Subset: **tuning only — develop here, then freeze before holdout**

==============================================================================
RESULTS — HARD eval  (15 questions, 2242.8s)
==============================================================================
Retrieval recall@10 (source):  100.0%  (13/13)
Retrieval recall@10 (pages):    92.3%  (12/13)
Retrieval MRR@10:              0.705
Retrieval nDCG@10:             0.745
Answer correctness (EQUIVALENT):    93.3%  (14/15)
  + partial credit:                 93.3%  (+ 0 PARTIAL)
  different:                       1
  errors:                          0
──────────────────────────────────────────────────────────────────────────────
Judge median relevance:           5/5
Judge median groundedness:        5/5
Judge median citation_accuracy:   5/5
Judge mean flip-rate (relevance): 0.000
Citation page-accuracy (avg):     0.992
──────────────────────────────────────────────────────────────────────────────
Critical errors:                  WRONG_EVIDENCE=1
==============================================================================

## Per-question

| ID | Type | recall src/pg | MRR | nDCG | rel/gnd/cit | cite-pg | Verdict | Question |
|---|---|---|---|---|---|---|---|---|
| h01 | page_lookup | ✓/✗ | 0.00 | 0.00 | 1/1/1 | 1.00 | DIFFERENT | What is described as KPI #5 in the 5 KPIs document, and on which page is it defi |
| h02 | page_lookup | ✓/✓ | 1.00 | 1.00 | 5/5/5 | 1.00 | EQUIVALENT | On what pages does the Why Do Coffee Shops Fail document discuss owner burnout? |
| h03 | page_lookup | ✓/✓ | 0.50 | 0.65 | 5/5/5 | 1.00 | EQUIVALENT | On which pages of '7 Costs That Sink Coffee Shops' is 'Employee Giveaways' cover |
| h04 | page_lookup | ✓/✓ | 0.33 | 0.58 | 5/5/5 | 1.00 | EQUIVALENT | Which page of the Calculating Your Break Even Point document contains the worked |
| h07 | synthesis | ✓/✓ | 0.50 | 0.69 | 5/4/4 | 1.00 | EQUIVALENT | Compare how the 'Briefing Doc - Opening and Operating a Profitable Coffee Shop'  |
| h08 | synthesis | ✓/✓ | 1.00 | 0.94 | 5/5/5 | 0.88 | EQUIVALENT | How do the '5 KPIs Every Clever Café Manager Should Track' and 'Top Metrics to T |
| h09 | synthesis | ✓/✓ | 1.00 | 0.89 | 5/5/5 | 1.00 | EQUIVALENT | Which cost categories appear in BOTH '7 Costs That Sink Coffee Shops' and 'How t |
| h12 | numeric | ✓/✓ | 1.00 | 0.88 | 5/5/5 | 1.00 | EQUIVALENT | What is the 2023 baseline annual revenue figure for Broadway Cafe in the financi |
| h13 | numeric | ✓/✓ | 0.50 | 0.63 | 5/5/5 | 1.00 | EQUIVALENT | What is the projected COGS percentage for Broadway Cafe in 2026, and what does i |
| h14 | numeric | ✓/✓ | 1.00 | 0.92 | 5/5/5 | 1.00 | EQUIVALENT | In the 'How to Determine the Cost of Selling 100 Coffees' document, what is the  |
| h17 | qa | ✓/✓ | 0.33 | 0.50 | 5/5/5 | 1.00 | EQUIVALENT | What does '7 Costs That Sink Coffee Shops' mean by 'The Cost of Time'? |
| h18 | qa | ✓/✓ | 1.00 | 1.00 | 5/4/5 | 1.00 | EQUIVALENT | What guidance does 'How to Revamp Your Coffee Shop Menu' give about menu length? |
| h19 | qa | ✓/✓ | 1.00 | 1.00 | 5/5/5 | 1.00 | EQUIVALENT | What are the tiebreaker rules in the Finalist Team Presentation Judging Rubric? |
| h22 | negative | — | — | — | 5/5/5 | 1.00 | EQUIVALENT | Do any of the materials discuss quantum computing applications for coffee shops? |
| h23 | negative | — | — | — | 5/5/5 | 1.00 | EQUIVALENT | Is there any discussion of NFTs or cryptocurrency-based loyalty tokens in the ma |

## Failures (DIFFERENT, PARTIAL, ERROR, or critical error)

### h01 — DIFFERENT  (page_lookup)
**Q:** What is described as KPI #5 in the 5 KPIs document, and on which page is it defined?
**Required sources:** [{'source': '5 KPIs Every Clever Café Manager Should Track', 'pages': [8]}]
**Recall:** {'applicable': True, 'source_full': True, 'pages_full': False, 'partial': 1.0, 'per_source': [{'source': '5 KPIs Every Clever Café Manager Should Track', 'wanted_pages': [8], 'source_hit': True, 'page_hit': False}]}
**MRR@10:** 0.0, **nDCG@10:** 0.0
**Judge:** {'relevance': 1, 'groundedness': 1, 'citation_accuracy': 1, 'critical_errors': ['WRONG_EVIDENCE'], 'short_rationale': "none of ['table turn', 'page 8'] present", 'flip_rate_relevance': 0.0, 'flip_rate_groundedness': 0.0, 'n_runs': 0, 'escalated': False, 'per_run': []}
**Citation validation:** {'n_citations': 2, 'n_source_valid': 2, 'n_page_valid': 2, 'source_accuracy': 1.0, 'page_accuracy': 1.0, 'per_citation': [{'source': '5 KPIs Every Clever Café Manager Should Track', 'pages': [1, 2, 3], 'raw': '[5 KPIs Every Clever Café Manager Should Track, pages 1-3]', 'source_exists': True, 'page_matches': True, 'valid': True}, {'source': '5 KPIs Every Clever Café Manager Should Track', 'pages': [4, 5, 6], 'raw': '[5 KPIs Every Clever Café Manager Should Track, pages 4-6]', 'source_exists': True, 'page_matches': True, 'valid': True}]}
**Retrieved:** [('5 KPIs Every Clever Café Manager Should Track', '[1, 2, 3]'), ('5 KPIs Every Clever Café Manager Should Track', '[4, 5, 6]'), ('High-Level Strategic Roadmap - Transforming a Declining Coffee Shop…', '[2]'), ('Briefing Doc - Opening and Operating a Profitable Coffee Shop', '[3, 4]'), ('High-Level Strategic Roadmap - Transforming a Declining Coffee Shop…', '[4]'), ('Broadway_Cafe_Financial_Model_Template S26', '[9, 10, 11, 12, 13, 14]'), ('Briefing Doc - Opening and Operating a Profitable Coffee Shop', '[6, 7]'), ('Appendix X AI Use Disclosure Team-Level — Manager Judgment Required', '[1]'), ('Broadway_Cafe_Financial_Model_User_Guide', '[2, 3]'), ('Broadway_Cafe_Financial_Model_Template S26', '[1, 2, 3]')]
**Expected:** KPI #5 is Table Turn Time, defined on page 8 of the 5 KPIs document.
**Got:** The provided context does not define KPI #5. The excerpts from that document cover only KPI #1, Employee Retention Rate — the percentage of employees who remain with the business over a given period [5 KPIs Every Clever Café Manager Should Track, pages 1-3] — and a section on RevPASH (revenue per available seat hour) [5 KPIs Every Clever Café Manager Should Track, pages 4-6].

The only mention of KPI #5 is an indirect cross-reference inside the RevPASH discussion, where the article suggests examining "how quickly patrons are seated (see KPI number 5 in our article)" [5 KPIs Every Clever Café M...
