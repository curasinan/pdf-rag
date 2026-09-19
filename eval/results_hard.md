# Eval Results — HARD

Run ID: `freeze2`
Subset: **all (tuning + holdout combined)**

==============================================================================
RESULTS — HARD eval  (25 questions, 119.4s)
==============================================================================
Retrieval recall@10 (source):  100.0%  (21/21)
Retrieval recall@10 (pages):    95.2%  (20/21)
Retrieval MRR@10:              0.746
Retrieval nDCG@10:             0.771
Answer correctness (EQUIVALENT):    96.0%  (24/25)
  + partial credit:                 96.0%  (+ 0 PARTIAL)
  different:                       1
  errors:                          0
──────────────────────────────────────────────────────────────────────────────
Judge median relevance:           5/5
Judge median groundedness:        5/5
Judge median citation_accuracy:   5/5
Judge mean flip-rate (relevance): 0.040
Citation page-accuracy (avg):     0.990
──────────────────────────────────────────────────────────────────────────────
Critical errors:                  FORMAT_FAIL=1
==============================================================================

## Per-question

| ID | Type | recall src/pg | MRR | nDCG | rel/gnd/cit | cite-pg | Verdict | Question |
|---|---|---|---|---|---|---|---|---|
| h01 | page_lookup | ✓/✗ | 0.00 | 0.00 | 1/1/1 | 1.00 | DIFFERENT | What is described as KPI #5 in the 5 KPIs document, and on which page is it defi |
| h02 | page_lookup | ✓/✓ | 1.00 | 1.00 | 5/5/5 | 1.00 | EQUIVALENT | On what pages does the Why Do Coffee Shops Fail document discuss owner burnout? |
| h03 | page_lookup | ✓/✓ | 0.50 | 0.65 | 5/5/5 | 1.00 | EQUIVALENT | On which pages of '7 Costs That Sink Coffee Shops' is 'Employee Giveaways' cover |
| h04 | page_lookup | ✓/✓ | 0.33 | 0.58 | 5/5/5 | 1.00 | EQUIVALENT | Which page of the Calculating Your Break Even Point document contains the worked |
| h05 | page_lookup | ✓/✓ | 1.00 | 1.00 | 5/5/5 | 1.00 | EQUIVALENT | Which pages of '5 KPIs' explain RevPASH and how it is calculated? |
| h06 | page_lookup | ✓/✓ | 1.00 | 1.00 | 4/5/5 | 1.00 | EQUIVALENT | On what page does '5 KPIs' first explicitly list 'Here are 5 KPIs every Clever C |
| h07 | synthesis | ✓/✓ | 0.50 | 0.69 | 5/4/4 | 1.00 | EQUIVALENT | Compare how the 'Briefing Doc - Opening and Operating a Profitable Coffee Shop'  |
| h08 | synthesis | ✓/✓ | 1.00 | 0.94 | 5/5/5 | 1.00 | EQUIVALENT | How do the '5 KPIs Every Clever Café Manager Should Track' and 'Top Metrics to T |
| h09 | synthesis | ✓/✓ | 1.00 | 0.89 | 5/4/4 | 1.00 | EQUIVALENT | Which cost categories appear in BOTH '7 Costs That Sink Coffee Shops' and 'How t |
| h10 | synthesis | ✓/✓ | 1.00 | 0.87 | 5/5/5 | 1.00 | EQUIVALENT | How does the High-Level Strategic Roadmap relate to the Business Plan Assumption |
| h11 | synthesis | ✓/✓ | 1.00 | 0.90 | 5/4/5 | 0.75 | EQUIVALENT | Both 'How to Increase Your Coffee Shop Profits with Loyalty Programs' and 'How T |
| h12 | numeric | ✓/✓ | 1.00 | 0.88 | 5/5/5 | 1.00 | EQUIVALENT | What is the 2023 baseline annual revenue figure for Broadway Cafe in the financi |
| h13 | numeric | ✓/✓ | 0.50 | 0.63 | 5/5/5 | 1.00 | EQUIVALENT | What is the projected COGS percentage for Broadway Cafe in 2026, and what does i |
| h14 | numeric | ✓/✓ | 1.00 | 0.92 | 5/5/5 | 1.00 | EQUIVALENT | In the 'How to Determine the Cost of Selling 100 Coffees' document, what is the  |
| h15 | numeric | ✓/✓ | 1.00 | 0.88 | 5/5/5 | 1.00 | EQUIVALENT | In the worked example in 'Calculating Your Break Even Point', what are the month |
| h16 | numeric | ✓/✓ | 0.17 | 0.36 | 5/5/5 | 1.00 | EQUIVALENT | How much funding does the Broadway Cafe financial model request in total? |
| h17 | qa | ✓/✓ | 0.33 | 0.50 | 5/5/5 | 1.00 | EQUIVALENT | What does '7 Costs That Sink Coffee Shops' mean by 'The Cost of Time'? |
| h18 | qa | ✓/✓ | 1.00 | 1.00 | 5/5/5 | 1.00 | EQUIVALENT | What guidance does 'How to Revamp Your Coffee Shop Menu' give about menu length? |
| h19 | qa | ✓/✓ | 1.00 | 1.00 | 5/5/5 | 1.00 | EQUIVALENT | What are the tiebreaker rules in the Finalist Team Presentation Judging Rubric? |
| h20 | qa | ✓/✓ | 1.00 | 1.00 | 5/5/5 | 1.00 | EQUIVALENT | What does the MIS 311 Team Accountability Checklist recommend for managing inter |
| h21 | qa | ✓/✓ | 0.33 | 0.50 | 5/5/5 | 1.00 | EQUIVALENT | What KPIs does the High-Level Strategic Roadmap propose for the modernization ph |
| h22 | negative | — | — | — | 5/5/5 | 1.00 | EQUIVALENT | Do any of the materials discuss quantum computing applications for coffee shops? |
| h23 | negative | — | — | — | 5/5/5 | 1.00 | EQUIVALENT | Is there any discussion of NFTs or cryptocurrency-based loyalty tokens in the ma |
| h24 | negative | — | — | — | 5/5/5 | 1.00 | EQUIVALENT | Do any of the documents cover pizza delivery operations? |
| h25 | negative | — | — | — | 5/5/5 | 1.00 | EQUIVALENT | Do the materials reference video game design principles applied to café customer |

## Failures (DIFFERENT, PARTIAL, ERROR, or critical error)

### h01 — DIFFERENT  (page_lookup)
**Q:** What is described as KPI #5 in the 5 KPIs document, and on which page is it defined?
**Required sources:** [{'source': '5 KPIs Every Clever Café Manager Should Track', 'pages': [8]}]
**Recall:** {'applicable': True, 'source_full': True, 'pages_full': False, 'partial': 1.0, 'per_source': [{'source': '5 KPIs Every Clever Café Manager Should Track', 'wanted_pages': [8], 'source_hit': True, 'page_hit': False}]}
**MRR@10:** 0.0, **nDCG@10:** 0.0
**Judge:** {'relevance': 1, 'groundedness': 1, 'citation_accuracy': 1, 'critical_errors': ['FORMAT_FAIL'], 'short_rationale': "none of ['table turn', 'page 8'] present; answer abstains (context-lack stated) — a retrieval miss, not a wrong assertion", 'flip_rate_relevance': 0.0, 'flip_rate_groundedness': 0.0, 'n_runs': 0, 'escalated': False, 'per_run': []}
**Citation validation:** {'n_citations': 2, 'n_source_valid': 2, 'n_page_valid': 2, 'source_accuracy': 1.0, 'page_accuracy': 1.0, 'per_citation': [{'source': '5 KPIs Every Clever Café Manager Should Track', 'pages': [1, 2, 3], 'raw': '[5 KPIs Every Clever Café Manager Should Track, pages 1-3]', 'source_exists': True, 'page_matches': True, 'valid': True}, {'source': '5 KPIs Every Clever Café Manager Should Track', 'pages': [4, 5, 6], 'raw': '[5 KPIs Every Clever Café Manager Should Track, pages 4-6]', 'source_exists': True, 'page_matches': True, 'valid': True}]}
**Retrieved:** [('5 KPIs Every Clever Café Manager Should Track', '[1, 2, 3]'), ('5 KPIs Every Clever Café Manager Should Track', '[4, 5, 6]'), ('High-Level Strategic Roadmap - Transforming a Declining Coffee Shop…', '[2]'), ('Briefing Doc - Opening and Operating a Profitable Coffee Shop', '[3, 4]'), ('High-Level Strategic Roadmap - Transforming a Declining Coffee Shop…', '[4]'), ('Broadway_Cafe_Financial_Model_Template S26', '[9, 10, 11, 12, 13, 14]'), ('Briefing Doc - Opening and Operating a Profitable Coffee Shop', '[6, 7]'), ('Appendix X AI Use Disclosure Team-Level — Manager Judgment Required', '[1]'), ('Broadway_Cafe_Financial_Model_User_Guide', '[2, 3]'), ('Broadway_Cafe_Financial_Model_Template S26', '[1, 2, 3]')]
**Expected:** KPI #5 is Table Turn Time, defined on page 8 of the 5 KPIs document.
**Got:** The provided context doesn't actually define KPI #5 — it only refers to it indirectly.

**What's in the context:**
- KPI #1 is identified explicitly: **Employee Retention Rate**, the percentage of employees that remain with the business over a given period [5 KPIs Every Clever Café Manager Should Track, pages 1-3].
- The RevPASH discussion mentions KPI #5 in passing, in the context of seating speed: "You could examine how quickly patrons are seated (see KPI number 5 in our article)" [5 KPIs Every Clever Café Manager Should Track, pages 4-6].

**What's missing:** The excerpt covering pages 4-6 ...
