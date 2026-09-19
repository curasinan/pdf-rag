# Eval Results — HARD

Run ID: `seed2`
Subset: **all (tuning + holdout combined)**

==============================================================================
RESULTS — HARD eval  (6 questions, 516.1s)
==============================================================================
Retrieval recall@10 (source):  100.0%  (6/6)
Retrieval recall@10 (pages):    83.3%  (5/6)
Retrieval MRR@10:              0.639
Retrieval nDCG@10:             0.706
Answer correctness (EQUIVALENT):    66.7%  (4/6)
  + partial credit:                 83.3%  (+ 1 PARTIAL)
  different:                       1
  errors:                          0
──────────────────────────────────────────────────────────────────────────────
Judge median relevance:           4.0/5
Judge median groundedness:        3.5/5
Judge median citation_accuracy:   2.5/5
Judge mean flip-rate (relevance): 0.167
Citation page-accuracy (avg):     1.000
──────────────────────────────────────────────────────────────────────────────
Critical errors:                  CITATION_WRONG=2, WRONG_EVIDENCE=1
==============================================================================

## Per-question

| ID | Type | recall src/pg | MRR | nDCG | rel/gnd/cit | cite-pg | Verdict | Question |
|---|---|---|---|---|---|---|---|---|
| h01 | page_lookup | ✓/✗ | 0.00 | 0.00 | 1/1/1 | 1.00 | DIFFERENT | What is described as KPI #5 in the 5 KPIs document, and on which page is it defi |
| h02 | page_lookup | ✓/✓ | 1.00 | 1.00 | 4/3/2 | 1.00 | EQUIVALENT | On what pages does the Why Do Coffee Shops Fail document discuss owner burnout? |
| h03 | page_lookup | ✓/✓ | 0.50 | 0.65 | 5/4/5 | 1.00 | EQUIVALENT | On which pages of '7 Costs That Sink Coffee Shops' is 'Employee Giveaways' cover |
| h04 | page_lookup | ✓/✓ | 0.33 | 0.58 | 4/3/2 | 1.00 | EQUIVALENT | Which page of the Calculating Your Break Even Point document contains the worked |
| h05 | page_lookup | ✓/✓ | 1.00 | 1.00 | 5/4/5 | 1.00 | EQUIVALENT | Which pages of '5 KPIs' explain RevPASH and how it is calculated? |
| h06 | page_lookup | ✓/✓ | 1.00 | 1.00 | 3/4/3 | 1.00 | PARTIAL | On what page does '5 KPIs' first explicitly list 'Here are 5 KPIs every Clever C |

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
**Got:** The provided context does not contain the definition of KPI #5 from that document.

What the context does include:

- **KPI #1 — Employee Retention Rate**, defined as "the percentage of employees that remain with the business over a given period" [5 KPIs Every Clever Café Manager Should Track, pages 1-3].
- An excerpt covering **RevPASH (revenue per available seat hour)**, including its formula and improvement tactics [5 KPIs Every Clever Café Manager Should Track, pages 4-6]. That excerpt is unnumbered in the context, so I can't confirm which KPI number it is.

The only reference to KPI #5 is...

### h02 — EQUIVALENT  (page_lookup)
**Q:** On what pages does the Why Do Coffee Shops Fail document discuss owner burnout?
**Required sources:** [{'source': 'Why Do Coffee Shops Fail', 'pages': [25, 26, 27]}]
**Recall:** {'applicable': True, 'source_full': True, 'pages_full': True, 'partial': 1.0, 'per_source': [{'source': 'Why Do Coffee Shops Fail', 'wanted_pages': [25, 26, 27], 'source_hit': True, 'page_hit': True}]}
**MRR@10:** 1.0, **nDCG@10:** 1.0
**Judge:** {'relevance': 4, 'groundedness': 3, 'citation_accuracy': 2, 'critical_errors': ['CITATION_WRONG'], 'short_rationale': "The core burnout discussion is on pages 24-27 per evidence (heading closes page 24 not 25, and continues to page 27), so the candidate's page ranges are shifted by one relative to the actual evidence chunk boundaries, misstating where content falls.", 'flip_rate_relevance': 0.0, 'flip_rate_groundedness': 0.0, 'n_runs': 2, 'escalated': False, 'per_run': [{'relevance': 4, 'groundedness': 3, 'citation_accuracy': 2, 'critical_errors': ['CITATION_WRONG'], 'short_rationale': "The core burnout discussion is on pages 24-27 per evidence (heading closes page 24 not 25, and continues to page 27), so the candidate's page ranges are shifted by one relative to the actual evidence chunk boundaries, misstating where content falls."}, {'relevance': 4, 'groundedness': 3, 'citation_accuracy': 2, 'critical_errors': ['CITATION_WRONG'], 'short_rationale': "The evidence's page-24 chunk covers only reasons 10–11 (debt, overestimating sales) and item 12 ('Coffee shop owner burnout') only appears as a heading at the very end of the pages-24-25 chunk with the actual burnout discussion in the pages-25-27 chunk, so citing 'Pages 24–25' as introducing/discuss"}]}
**Citation validation:** {'n_citations': 3, 'n_source_valid': 3, 'n_page_valid': 3, 'source_accuracy': 1.0, 'page_accuracy': 1.0, 'per_citation': [{'source': 'Why Do Coffee Shops Fail', 'pages': [24, 25], 'raw': '[Why Do Coffee Shops Fail, pages 24-25]', 'source_exists': True, 'page_matches': True, 'valid': True}, {'source': 'Why Do Coffee Shops Fail', 'pages': [25, 26, 27], 'raw': '[Why Do Coffee Shops Fail, pages 25-27]', 'source_exists': True, 'page_matches': True, 'valid': True}, {'source': 'Why Do Coffee Shops Fail', 'pages': [27, 28, 29], 'raw': '[Why Do Coffee Shops Fail, pages 27-29]', 'source_exists': True, 'page_matches': True, 'valid': True}]}
**Retrieved:** [('Why Do Coffee Shops Fail', '[25, 26, 27]'), ('Why Do Coffee Shops Fail', '[27, 28, 29]'), ('Why Do Coffee Shops Fail', '[24, 25]'), ('Why Do Coffee Shops Fail', '[5, 6, 7, 8]'), ('Why Do Coffee Shops Fail', '[22, 23, 24]'), ('Why Do Coffee Shops Fail', '[11, 12, 13, 14, 15]'), ('Why Do Coffee Shops Fail', '[19, 20, 21, 22]'), ('Why Do Coffee Shops Fail', '[1, 2, 3, 4, 5]'), ('Why Do Coffee Shops Fail', '[16, 17, 18, 19]'), ('Why Do Coffee Shops Fail', '[8, 9, 10, 11]')]
**Expected:** Owner burnout is discussed on pages 25-26 of Why Do Coffee Shops Fail (the heading 'Reasons Why Coffee Shops Fail: 12. Coffee shop owner burnout' closes page 25 and the discussion runs on page 26). Page 27 repeats 'Coffee shop owner burnout.' in the summary list, so an answer that also cites page 27 is correct.
**Got:** Owner burnout is discussed in the following places:

- **Pages 24–25** — introduces "Reasons Why Coffee Shops Fail: 12. Coffee shop owner burnout," noting that "being in love with the idea of having a coffee shop and not understanding the work involved can quickly turn your enthusiasm into burnout" [Why Do Coffee Shops Fail, pages 24-25].
- **Pages 25–27** — the main treatment: how often burnout happens, that many new owners experience it within the first two years, its causes (difficulty of opening, unexpected growth and growing pains, neglecting personal life, managing employees), its conseq...

### h04 — EQUIVALENT  (page_lookup)
**Q:** Which page of the Calculating Your Break Even Point document contains the worked example with concrete numbers?
**Required sources:** [{'source': 'Calculating Your Break Even Point', 'pages': [2, 3, 4]}]
**Recall:** {'applicable': True, 'source_full': True, 'pages_full': True, 'partial': 1.0, 'per_source': [{'source': 'Calculating Your Break Even Point', 'wanted_pages': [2, 3, 4], 'source_hit': True, 'page_hit': True}]}
**MRR@10:** 0.3333333333333333, **nDCG@10:** 0.5833416105149332
**Judge:** {'relevance': 4, 'groundedness': 3, 'citation_accuracy': 2, 'critical_errors': ['CITATION_WRONG'], 'short_rationale': "The candidate correctly identifies the pages 2-4 range and numbers but fabricates a specific 'page 4-5' citation for the Americano cost example that evidence shows is actually within the pages 2-4 chunk, and its final 'page 3' inference is presented with hedging but still risks misattribution since ", 'flip_rate_relevance': 1.0, 'flip_rate_groundedness': 1.0, 'n_runs': 3, 'escalated': False, 'per_run': [{'relevance': 4, 'groundedness': 3, 'citation_accuracy': 2, 'critical_errors': ['CITATION_WRONG'], 'short_rationale': "The candidate correctly identifies the pages 2-4 range and numbers but fabricates a specific 'page 4-5' citation for the Americano cost example that evidence shows is actually within the pages 2-4 chunk, and its final 'page 3' inference is presented with hedging but still risks misattribution since "}, {'relevance': 3, 'groundedness': 4, 'citation_accuracy': 4, 'critical_errors': ['NONE'], 'short_rationale': "The candidate correctly hedges that the example spans pages 2-4 and cites accurate content, but then undermines this by offering an inferred single-page answer ('page 3') not directly stated in the evidence, adding minor unwarranted precision."}, {'relevance': 4, 'groundedness': 3, 'citation_accuracy': 2, 'critical_errors': ['CITATION_WRONG'], 'short_rationale': "The reference-answer numbers ($7,200, $522, $208, $2.75 Americano) are correctly grounded, but the candidate cites the Americano cost-breakdown example as being on 'pages 4–5' of 'Calculating Your Break Even Point' when that $0.50/$0.27/$0.77/$2.75 example actually appears within the 'pages 2-4' chu"}]}
**Citation validation:** {'n_citations': 3, 'n_source_valid': 3, 'n_page_valid': 3, 'source_accuracy': 1.0, 'page_accuracy': 1.0, 'per_citation': [{'source': 'Calculating Your Break Even Point', 'pages': [2, 3, 4], 'raw': '[Calculating Your Break Even Point, pages 2-4]', 'source_exists': True, 'page_matches': True, 'valid': True}, {'source': 'Calculating Your Break Even Point', 'pages': [1, 2, 3], 'raw': '[Calculating Your Break Even Point, pages 1-3]', 'source_exists': True, 'page_matches': True, 'valid': True}, {'source': 'Calculating Your Break Even Point', 'pages': [4, 5], 'raw': '[Calculating Your Break Even Point, pages 4-5]', 'source_exists': True, 'page_matches': True, 'valid': True}]}
**Retrieved:** [('Briefing Doc - Opening and Operating a Profitable Coffee Shop', '[4, 5]'), ('Briefing Doc - Opening and Operating a Profitable Coffee Shop', '[1, 2, 3]'), ('Calculating Your Break Even Point', '[1, 2, 3]'), ('Briefing Doc - Opening and Operating a Profitable Coffee Shop', '[6, 7]'), ('Calculating Your Break Even Point', '[4, 5]'), ('Calculating Your Break Even Point', '[2, 3, 4]'), ('Briefing Doc - Opening and Operating a Profitable Coffee Shop', '[3]'), ('Briefing Doc - Opening and Operating a Profitable Coffee Shop', '[3, 4]'), ('Broadway_Cafe_Financial_Model_User_Guide', '[2, 3]'), ('Broadway_Cafe_Financial_Model_User_Guide', '[1]')]
**Expected:** The worked example spans pages 2-4 (synthetic DOCX pages). Page 2 sets up the startup-cost scenario; page 3 carries the core figures — $7,200 monthly fixed costs (rent $2,000, insurance $300, loan $350, salary $4,200), $2,800 variable costs, and $4.35 x 12 x 10 = $522 daily gross revenue; page 4 completes it with $522 - $333 = $208 net revenue. An answer naming pages 2-4, or page 3 as the page with the concrete numbers, is correct; the question's singular 'which page' is imprecise because the example genuinely spans a range.
**Got:** The worked example with concrete numbers runs across the middle of the document rather than sitting on one page — the available citations are page ranges, so an exact single page can't be pinpointed.

**The main worked example: pages 2–4**

- Sample startup costs — Legal and Administrative $300, Coffee Equipment $12,000, Remodeling and Buildout $4,500, Furniture and Fixtures $2,500, Other $2,500, for an initial total of $21,800, with $10,000 financed at a $350 monthly payment [Calculating Your Break Even Point, pages 2-4]
- Operational costs — fixed costs of $7,200/month (rent $2,000, insuranc...

### h06 — PARTIAL  (page_lookup)
**Q:** On what page does '5 KPIs' first explicitly list 'Here are 5 KPIs every Clever Café manager should track'?
**Required sources:** [{'source': '5 KPIs Every Clever Café Manager Should Track', 'pages': [2]}]
**Recall:** {'applicable': True, 'source_full': True, 'pages_full': True, 'partial': 1.0, 'per_source': [{'source': '5 KPIs Every Clever Café Manager Should Track', 'wanted_pages': [2], 'source_hit': True, 'page_hit': True}]}
**MRR@10:** 1.0, **nDCG@10:** 1.0
**Judge:** {'relevance': 3, 'groundedness': 4, 'citation_accuracy': 3, 'critical_errors': ['NONE'], 'short_rationale': 'The reference answer places the line on page 2, but the candidate cites only the aggregated pages 1-3 range and explicitly declines to pin down a specific page, so it fails to provide the correct page-level citation the question asked for.', 'flip_rate_relevance': 0.0, 'flip_rate_groundedness': 0.5, 'n_runs': 3, 'escalated': True, 'per_run': [{'relevance': 3, 'groundedness': 3, 'citation_accuracy': 2, 'critical_errors': ['CITATION_WRONG'], 'short_rationale': 'The reference answer places the line on page 2, but the candidate cites only the aggregated pages 1-3 range and explicitly declines to pin down a specific page, so it fails to provide the correct page-level citation the question asked for.'}, {'relevance': 3, 'groundedness': 4, 'citation_accuracy': 3, 'critical_errors': ['NONE'], 'short_rationale': "The candidate correctly declines to guess a single page but only cites the broad 'pages 1-3' range rather than pinpointing page 2 as the reference answer does, making the response incomplete relative to user intent."}, {'relevance': 3, 'groundedness': 4, 'citation_accuracy': 3, 'critical_errors': ['NONE'], 'short_rationale': "The candidate correctly declines to guess an exact page but only cites the broad 'pages 1-3' range rather than pinpointing page 2 as the reference answer does, leaving the core question unanswered."}]}
**Citation validation:** {'n_citations': 1, 'n_source_valid': 1, 'n_page_valid': 1, 'source_accuracy': 1.0, 'page_accuracy': 1.0, 'per_citation': [{'source': '5 KPIs Every Clever Café Manager Should Track', 'pages': [1, 2, 3], 'raw': '[5 KPIs Every Clever Café Manager Should Track, pages 1-3]', 'source_exists': True, 'page_matches': True, 'valid': True}]}
**Retrieved:** [('5 KPIs Every Clever Café Manager Should Track', '[1, 2, 3]'), ('5 KPIs Every Clever Café Manager Should Track', '[6, 7]'), ('Briefing Doc - Opening and Operating a Profitable Coffee Shop', '[3, 4]'), ('7 Costs That Sink Coffee Shops', '[17, 18, 19]'), ('Broadway_Cafe_Financial_Model_User_Guide', '[2, 3]'), ('Top Metrics to Track to Measure Your Coffee Shop Franchise’s Performance', '[3, 4, 5, 6]'), ('Top Metrics to Track to Measure Your Coffee Shop Franchise’s Performance', '[1, 2, 3]'), ('Broadway_Cafe_Financial_Model_User_Guide', '[1]'), ('Briefing Doc - Opening and Operating a Profitable Coffee Shop', '[1, 2, 3]'), ('7 Costs That Sink Coffee Shops', '[8, 9, 10, 11]')]
**Expected:** The explicit '5 KPIs' framing appears on page 2 of the document, immediately followed by KPI #1 Employee Retention Rate.
**Got:** The phrase "Here are 5 KPIs every Clever Café manager should track:" appears in the chunk covering the opening of the article, immediately before the "1. Employee Retention Rate" section [5 KPIs Every Clever Café Manager Should Track, pages 1-3].

The context does not pin it to a single page number — that excerpt is provided as a combined range (pages 1-3), so I can't tell from what's given whether the line falls on page 1, 2, or 3. Based on its position (after the introduction and just before the first KPI heading), it is most likely near the end of that range, but the source as provided does...
