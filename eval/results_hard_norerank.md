# Eval Results — HARD

Run ID: `norerank1`
Subset: **tuning only — develop here, then freeze before holdout**

> **RERANK DISABLED** (`--no-rerank`) — retrieval is RRF order only. Not comparable to a default run.

==============================================================================
RESULTS — HARD eval  (15 questions, 2173.0s)
==============================================================================
Retrieval recall@10 (source):  100.0%  (13/13)
Retrieval recall@10 (pages):    92.3%  (12/13)
Retrieval MRR@10:              0.885
Retrieval nDCG@10:             0.847
Answer correctness (EQUIVALENT):    86.7%  (13/15)
  + partial credit:                 93.3%  (+ 1 PARTIAL)
  different:                       1
  errors:                          0
──────────────────────────────────────────────────────────────────────────────
Judge median relevance:           5/5
Judge median groundedness:        5/5
Judge median citation_accuracy:   5/5
Judge mean flip-rate (relevance): 0.000
Citation page-accuracy (avg):     1.000
──────────────────────────────────────────────────────────────────────────────
Critical errors:                  WRONG_EVIDENCE=1
==============================================================================

## Per-question

| ID | Type | recall src/pg | MRR | nDCG | rel/gnd/cit | cite-pg | Verdict | Question |
|---|---|---|---|---|---|---|---|---|
| h01 | page_lookup | ✓/✗ | 0.00 | 0.00 | 3/3/3 | 1.00 | PARTIAL | What is described as KPI #5 in the 5 KPIs document, and on which page is it defi |
| h02 | page_lookup | ✓/✓ | 1.00 | 1.00 | 5/5/5 | 1.00 | EQUIVALENT | On what pages does the Why Do Coffee Shops Fail document discuss owner burnout? |
| h03 | page_lookup | ✓/✓ | 1.00 | 1.00 | 5/4/5 | 1.00 | EQUIVALENT | On which pages of '7 Costs That Sink Coffee Shops' is 'Employee Giveaways' cover |
| h04 | page_lookup | ✓/✓ | 1.00 | 0.92 | 1/1/1 | 1.00 | DIFFERENT | Which page of the Calculating Your Break Even Point document contains the worked |
| h07 | synthesis | ✓/✓ | 1.00 | 0.86 | 5/4/4 | 1.00 | EQUIVALENT | Compare how the 'Briefing Doc - Opening and Operating a Profitable Coffee Shop'  |
| h08 | synthesis | ✓/✓ | 1.00 | 0.91 | 5/5/5 | 1.00 | EQUIVALENT | How do the '5 KPIs Every Clever Café Manager Should Track' and 'Top Metrics to T |
| h09 | synthesis | ✓/✓ | 1.00 | 0.96 | 5/5/5 | 1.00 | EQUIVALENT | Which cost categories appear in BOTH '7 Costs That Sink Coffee Shops' and 'How t |
| h12 | numeric | ✓/✓ | 1.00 | 0.88 | 5/5/5 | 1.00 | EQUIVALENT | What is the 2023 baseline annual revenue figure for Broadway Cafe in the financi |
| h13 | numeric | ✓/✓ | 1.00 | 0.85 | 5/5/5 | 1.00 | EQUIVALENT | What is the projected COGS percentage for Broadway Cafe in 2026, and what does i |
| h14 | numeric | ✓/✓ | 1.00 | 1.00 | 5/5/5 | 1.00 | EQUIVALENT | In the 'How to Determine the Cost of Selling 100 Coffees' document, what is the  |
| h17 | qa | ✓/✓ | 1.00 | 1.00 | 5/5/5 | 1.00 | EQUIVALENT | What does '7 Costs That Sink Coffee Shops' mean by 'The Cost of Time'? |
| h18 | qa | ✓/✓ | 0.50 | 0.63 | 5/5/5 | 1.00 | EQUIVALENT | What guidance does 'How to Revamp Your Coffee Shop Menu' give about menu length? |
| h19 | qa | ✓/✓ | 1.00 | 1.00 | 5/5/5 | 1.00 | EQUIVALENT | What are the tiebreaker rules in the Finalist Team Presentation Judging Rubric? |
| h22 | negative | — | — | — | 5/5/5 | 1.00 | EQUIVALENT | Do any of the materials discuss quantum computing applications for coffee shops? |
| h23 | negative | — | — | — | 5/5/5 | 1.00 | EQUIVALENT | Is there any discussion of NFTs or cryptocurrency-based loyalty tokens in the ma |

## Failures (DIFFERENT, PARTIAL, ERROR, or critical error)

### h01 — PARTIAL  (page_lookup)
**Q:** What is described as KPI #5 in the 5 KPIs document, and on which page is it defined?
**Required sources:** [{'source': '5 KPIs Every Clever Café Manager Should Track', 'pages': [8]}]
**Recall:** {'applicable': True, 'source_full': True, 'pages_full': False, 'partial': 1.0, 'per_source': [{'source': '5 KPIs Every Clever Café Manager Should Track', 'wanted_pages': [8], 'source_hit': True, 'page_hit': False}]}
**MRR@10:** 0.0, **nDCG@10:** 0.0
**Judge:** {'relevance': 3, 'groundedness': 3, 'citation_accuracy': 3, 'critical_errors': ['NONE'], 'short_rationale': "missing ['table turn']", 'flip_rate_relevance': 0.0, 'flip_rate_groundedness': 0.0, 'n_runs': 0, 'escalated': False, 'per_run': []}
**Citation validation:** {'n_citations': 2, 'n_source_valid': 2, 'n_page_valid': 2, 'source_accuracy': 1.0, 'page_accuracy': 1.0, 'per_citation': [{'source': '5 KPIs Every Clever Café Manager Should Track', 'pages': [1, 2, 3], 'raw': '[5 KPIs Every Clever Café Manager Should Track, pages 1-3]', 'source_exists': True, 'page_matches': True, 'valid': True}, {'source': '5 KPIs Every Clever Café Manager Should Track', 'pages': [6, 7], 'raw': '[5 KPIs Every Clever Café Manager Should Track, pages 6-7]', 'source_exists': True, 'page_matches': True, 'valid': True}]}
**Retrieved:** [('5 KPIs Every Clever Café Manager Should Track', '[1, 2, 3]'), ('Broadway_Cafe_Financial_Model_User_Guide', '[1]'), ('Top Metrics to Track to Measure Your Coffee Shop Franchise’s Performance', '[1, 2, 3]'), ('Briefing Doc - Opening and Operating a Profitable Coffee Shop', '[3, 4]'), ('Broadway_Cafe_Financial_Model_User_Guide', '[2, 3]'), ('Student “How to Earn an A” One-Page Guide S26', '[2, 3]'), ('Student “How to Earn an A” One-Page Guide S26', '[3, 4]'), ('5 KPIs Every Clever Café Manager Should Track', '[6, 7]'), ('Top Metrics to Track to Measure Your Coffee Shop Franchise’s Performance', '[3, 4, 5, 6]'), ('Briefing Doc - Opening and Operating a Profitable Coffee Shop', '[6, 7]')]
**Expected:** KPI #5 is Table Turn Time, defined on page 8 of the 5 KPIs document.
**Got:** The provided context doesn't contain KPI #5 from that document. The excerpts available from *5 KPIs Every Clever Café Manager Should Track* cover only:

- **#1. Employee Retention Rate** — the percentage of employees who remain with the business over a given period [5 KPIs Every Clever Café Manager Should Track, pages 1-3]
- **#3. Labour Cost Percentage** and **#4. Revenue by Employee** [5 KPIs Every Clever Café Manager Should Track, pages 6-7]

KPI #2 and KPI #5 fall on pages not included in the excerpts (pages 4-5 and page 8 onward), so I can't tell you what #5 is or cite its page. If you ca...

### h04 — DIFFERENT  (page_lookup)
**Q:** Which page of the Calculating Your Break Even Point document contains the worked example with concrete numbers?
**Required sources:** [{'source': 'Calculating Your Break Even Point', 'pages': [2, 3, 4]}]
**Recall:** {'applicable': True, 'source_full': True, 'pages_full': True, 'partial': 1.0, 'per_source': [{'source': 'Calculating Your Break Even Point', 'wanted_pages': [2, 3, 4], 'source_hit': True, 'page_hit': True}]}
**MRR@10:** 1.0, **nDCG@10:** 0.9197207891481876
**Judge:** {'relevance': 1, 'groundedness': 1, 'citation_accuracy': 1, 'critical_errors': ['WRONG_EVIDENCE'], 'short_rationale': "none of ['7,200', '522'] present", 'flip_rate_relevance': 0.0, 'flip_rate_groundedness': 0.0, 'n_runs': 0, 'escalated': False, 'per_run': []}
**Citation validation:** {'n_citations': 3, 'n_source_valid': 3, 'n_page_valid': 3, 'source_accuracy': 1.0, 'page_accuracy': 1.0, 'per_citation': [{'source': 'Calculating Your Break Even Point', 'pages': [1, 2, 3], 'raw': '[Calculating Your Break Even Point, pages 1-3]', 'source_exists': True, 'page_matches': True, 'valid': True}, {'source': 'Calculating Your Break Even Point', 'pages': [4, 5], 'raw': '[Calculating Your Break Even Point, pages 4-5]', 'source_exists': True, 'page_matches': True, 'valid': True}, {'source': 'Briefing Doc - Opening and Operating a Profitable Coffee Shop', 'pages': [4, 5], 'raw': '[Briefing Doc - Opening and Operating a Profitable Coffee Shop, pages 4-5]', 'source_exists': True, 'page_matches': True, 'valid': True}]}
**Retrieved:** [('Calculating Your Break Even Point', '[1, 2, 3]'), ('Briefing Doc - Opening and Operating a Profitable Coffee Shop', '[6, 7]'), ('Calculating Your Break Even Point', '[4, 5]'), ('Briefing Doc - Opening and Operating a Profitable Coffee Shop', '[3]'), ('Briefing Doc - Opening and Operating a Profitable Coffee Shop', '[4, 5]'), ('Student “How to Earn an A” One-Page Guide S26', '[2, 3]'), ('Briefing Doc - Opening and Operating a Profitable Coffee Shop', '[5, 6]'), ('Student “How to Earn an A” One-Page Guide S26', '[1, 2]'), ('How To Understand Your Customers And Their Needs With The Right Data', '[3, 4, 5]'), ('How To Understand Your Customers And Their Needs With The Right Data', '[6]')]
**Expected:** The worked example spans pages 2-4 (synthetic DOCX pages). Page 2 sets up the startup-cost scenario; page 3 carries the core figures — $7,200 monthly fixed costs (rent $2,000, insurance $300, loan $350, salary $4,200), $2,800 variable costs, and $4.35 x 12 x 10 = $522 daily gross revenue; page 4 completes it with $522 - $333 = $208 net revenue. An answer naming pages 2-4, or page 3 as the page with the concrete numbers, is correct; the question's singular 'which page' is imprecise because the example genuinely spans a range.
**Got:** The context is chunked by page range, not by individual page, so I can't pinpoint a single page number — but there are two worked examples with concrete numbers, in two different ranges:

**1. The startup cost scenario — [Calculating Your Break Even Point, pages 1-3]**
Legal and Administrative: $300; Coffee Equipment: $12,000; Remodeling and Buildout: $4,500; Furniture and Fixtures: $2,500; Other Costs: $2,500 — for Initial Total Startup Costs of $21,800, with an assumed $10,000 borrowed at a $350 monthly payment [Calculating Your Break Even Point, pages 1-3].

**2. The per-item margin example...
