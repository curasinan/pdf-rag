# Eval Results — HARD

Run ID: `full1`
Subset: **all (tuning + holdout combined)**

==============================================================================
RESULTS — HARD eval  (25 questions, 1591.4s)
==============================================================================
Retrieval recall@10 (source):  100.0%  (21/21)
Retrieval recall@10 (pages):    95.2%  (20/21)
Retrieval MRR@10:              0.746
Retrieval nDCG@10:             0.764
Answer correctness (EQUIVALENT):    92.0%  (23/25)
  + partial credit:                100.0%  (+ 2 PARTIAL)
  different:                       0
  errors:                          0
──────────────────────────────────────────────────────────────────────────────
Judge median relevance:           5/5
Judge median groundedness:        5/5
Judge median citation_accuracy:   5/5
Judge mean flip-rate (relevance): 0.000
Citation page-accuracy (avg):     0.963
──────────────────────────────────────────────────────────────────────────────
Critical errors:                  CITATION_WRONG=3, HALLUCINATION=2
==============================================================================

## Per-question

| ID | Type | recall src/pg | MRR | nDCG | rel/gnd/cit | cite-pg | Verdict | Question |
|---|---|---|---|---|---|---|---|---|
| h01 | page_lookup | ✓/✗ | 0.00 | 0.00 | 3/3/3 | 1.00 | PARTIAL | What is described as KPI #5 in the 5 KPIs document, and on which page is it defi |
| h02 | page_lookup | ✓/✓ | 1.00 | 1.00 | 4/4/3 | 1.00 | EQUIVALENT | On what pages does the Why Do Coffee Shops Fail document discuss owner burnout? |
| h03 | page_lookup | ✓/✓ | 0.50 | 0.65 | 5/3/5 | 1.00 | EQUIVALENT | On which pages of '7 Costs That Sink Coffee Shops' is 'Employee Giveaways' cover |
| h04 | page_lookup | ✓/✓ | 0.33 | 0.58 | 4/4/4 | 1.00 | EQUIVALENT | Which page of the Calculating Your Break Even Point document contains the worked |
| h05 | page_lookup | ✓/✓ | 1.00 | 1.00 | 4/3/3 | 1.00 | EQUIVALENT | Which pages of '5 KPIs' explain RevPASH and how it is calculated? |
| h06 | page_lookup | ✓/✓ | 1.00 | 1.00 | 3/4/4 | 1.00 | PARTIAL | On what page does '5 KPIs' first explicitly list 'Here are 5 KPIs every Clever C |
| h07 | synthesis | ✓/✓ | 0.50 | 0.69 | 5/4/4 | 0.86 | EQUIVALENT | Compare how the 'Briefing Doc - Opening and Operating a Profitable Coffee Shop'  |
| h08 | synthesis | ✓/✓ | 1.00 | 0.94 | 5/5/5 | 0.83 | EQUIVALENT | How do the '5 KPIs Every Clever Café Manager Should Track' and 'Top Metrics to T |
| h09 | synthesis | ✓/✓ | 1.00 | 0.89 | 5/4/4 | 1.00 | EQUIVALENT | Which cost categories appear in BOTH '7 Costs That Sink Coffee Shops' and 'How t |
| h10 | synthesis | ✓/✓ | 1.00 | 0.87 | 5/5/5 | 1.00 | EQUIVALENT | How does the High-Level Strategic Roadmap relate to the Business Plan Assumption |
| h11 | synthesis | ✓/✓ | 1.00 | 0.90 | 5/4/4 | 0.75 | EQUIVALENT | Both 'How to Increase Your Coffee Shop Profits with Loyalty Programs' and 'How T |
| h12 | numeric | ✓/✓ | 1.00 | 0.88 | 5/5/5 | 1.00 | EQUIVALENT | What is the 2023 baseline annual revenue figure for Broadway Cafe in the financi |
| h13 | numeric | ✓/✓ | 0.50 | 0.63 | 5/5/5 | 1.00 | EQUIVALENT | What is the projected COGS percentage for Broadway Cafe in 2026, and what does i |
| h14 | numeric | ✓/✓ | 1.00 | 0.92 | 5/5/5 | 1.00 | EQUIVALENT | In the 'How to Determine the Cost of Selling 100 Coffees' document, what is the  |
| h15 | numeric | ✓/✓ | 1.00 | 0.88 | 5/5/5 | 1.00 | EQUIVALENT | In the worked example in 'Calculating Your Break Even Point', what are the month |
| h16 | numeric | ✓/✓ | 0.17 | 0.36 | 5/5/5 | 1.00 | EQUIVALENT | How much funding does the Broadway Cafe financial model request in total? |
| h17 | qa | ✓/✓ | 0.33 | 0.50 | 5/5/5 | 1.00 | EQUIVALENT | What does '7 Costs That Sink Coffee Shops' mean by 'The Cost of Time'? |
| h18 | qa | ✓/✓ | 1.00 | 0.85 | 5/5/5 | 1.00 | EQUIVALENT | What guidance does 'How to Revamp Your Coffee Shop Menu' give about menu length? |
| h19 | qa | ✓/✓ | 1.00 | 1.00 | 5/5/5 | 1.00 | EQUIVALENT | What are the tiebreaker rules in the Finalist Team Presentation Judging Rubric? |
| h20 | qa | ✓/✓ | 1.00 | 1.00 | 5/5/5 | 1.00 | EQUIVALENT | What does the MIS 311 Team Accountability Checklist recommend for managing inter |
| h21 | qa | ✓/✓ | 0.33 | 0.50 | 5/5/5 | 0.80 | EQUIVALENT | What KPIs does the High-Level Strategic Roadmap propose for the modernization ph |
| h22 | negative | — | — | — | 5/5/5 | 1.00 | EQUIVALENT | Do any of the materials discuss quantum computing applications for coffee shops? |
| h23 | negative | — | — | — | 5/5/5 | 1.00 | EQUIVALENT | Is there any discussion of NFTs or cryptocurrency-based loyalty tokens in the ma |
| h24 | negative | — | — | — | 5/5/5 | 0.83 | EQUIVALENT | Do any of the documents cover pizza delivery operations? |
| h25 | negative | — | — | — | 5/5/5 | 1.00 | EQUIVALENT | Do the materials reference video game design principles applied to café customer |

## Failures (DIFFERENT, PARTIAL, ERROR, or critical error)

### h01 — PARTIAL  (page_lookup)
**Q:** What is described as KPI #5 in the 5 KPIs document, and on which page is it defined?
**Required sources:** [{'source': '5 KPIs Every Clever Café Manager Should Track', 'pages': [8]}]
**Recall:** {'applicable': True, 'source_full': True, 'pages_full': False, 'partial': 1.0, 'per_source': [{'source': '5 KPIs Every Clever Café Manager Should Track', 'wanted_pages': [8], 'source_hit': True, 'page_hit': False}]}
**MRR@10:** 0.0, **nDCG@10:** 0.0
**Judge:** {'relevance': 3, 'groundedness': 3, 'citation_accuracy': 3, 'critical_errors': ['NONE'], 'short_rationale': "missing ['page 8']", 'flip_rate_relevance': 0.0, 'flip_rate_groundedness': 0.0, 'n_runs': 0, 'escalated': False, 'per_run': []}
**Citation validation:** {'n_citations': 2, 'n_source_valid': 2, 'n_page_valid': 2, 'source_accuracy': 1.0, 'page_accuracy': 1.0, 'per_citation': [{'source': '5 KPIs Every Clever Café Manager Should Track', 'pages': [4, 5, 6], 'raw': '[5 KPIs Every Clever Café Manager Should Track, pages 4-6]', 'source_exists': True, 'page_matches': True, 'valid': True}, {'source': '5 KPIs Every Clever Café Manager Should Track', 'pages': [1, 2, 3], 'raw': '[5 KPIs Every Clever Café Manager Should Track, pages 1-3]', 'source_exists': True, 'page_matches': True, 'valid': True}]}
**Retrieved:** [('5 KPIs Every Clever Café Manager Should Track', '[1, 2, 3]'), ('5 KPIs Every Clever Café Manager Should Track', '[4, 5, 6]'), ('High-Level Strategic Roadmap - Transforming a Declining Coffee Shop…', '[2]'), ('Briefing Doc - Opening and Operating a Profitable Coffee Shop', '[3, 4]'), ('High-Level Strategic Roadmap - Transforming a Declining Coffee Shop…', '[4]'), ('Broadway_Cafe_Financial_Model_Template S26', '[9, 10, 11, 12, 13, 14]'), ('Briefing Doc - Opening and Operating a Profitable Coffee Shop', '[6, 7]'), ('Appendix X AI Use Disclosure Team-Level — Manager Judgment Required', '[1]'), ('Broadway_Cafe_Financial_Model_User_Guide', '[2, 3]'), ('Broadway_Cafe_Financial_Model_Template S26', '[1, 2, 3]')]
**Expected:** KPI #5 is Table Turn Time, defined on page 8 of the 5 KPIs document.
**Got:** The provided context does not define KPI #5. It's referenced but never stated.

The only mention is a cross-reference inside the RevPASH discussion: when suggesting ways to improve RevPASH during busy periods, the document says you could "examine how quickly patrons are seated (see KPI number 5 in our article)" [5 KPIs Every Clever Café Manager Should Track, pages 4-6]. That implies KPI #5 relates to seating speed/table turn time, but the excerpt stops short of the section that actually names and defines it.

What the context does cover from that document:
- **KPI #1 — Employee Retention Rate*...

### h02 — EQUIVALENT  (page_lookup)
**Q:** On what pages does the Why Do Coffee Shops Fail document discuss owner burnout?
**Required sources:** [{'source': 'Why Do Coffee Shops Fail', 'pages': [25, 26, 27]}]
**Recall:** {'applicable': True, 'source_full': True, 'pages_full': True, 'partial': 1.0, 'per_source': [{'source': 'Why Do Coffee Shops Fail', 'wanted_pages': [25, 26, 27], 'source_hit': True, 'page_hit': True}]}
**MRR@10:** 1.0, **nDCG@10:** 1.0
**Judge:** {'relevance': 4, 'groundedness': 4, 'citation_accuracy': 3, 'critical_errors': ['CITATION_WRONG'], 'short_rationale': "The candidate's page ranges (24-25, 25-27, 27-29) are shifted from the reference (25-26 for intro/discussion, page 27 for the summary mention), though the correct section header and content are captured.", 'flip_rate_relevance': 0.0, 'flip_rate_groundedness': 0.0, 'n_runs': 1, 'escalated': False, 'per_run': [{'relevance': 4, 'groundedness': 4, 'citation_accuracy': 3, 'critical_errors': ['CITATION_WRONG'], 'short_rationale': "The candidate's page ranges (24-25, 25-27, 27-29) are shifted from the reference (25-26 for intro/discussion, page 27 for the summary mention), though the correct section header and content are captured."}]}
**Citation validation:** {'n_citations': 3, 'n_source_valid': 3, 'n_page_valid': 3, 'source_accuracy': 1.0, 'page_accuracy': 1.0, 'per_citation': [{'source': 'Why Do Coffee Shops Fail', 'pages': [24, 25], 'raw': '[Why Do Coffee Shops Fail, pages 24-25]', 'source_exists': True, 'page_matches': True, 'valid': True}, {'source': 'Why Do Coffee Shops Fail', 'pages': [25, 26, 27], 'raw': '[Why Do Coffee Shops Fail, pages 25-27]', 'source_exists': True, 'page_matches': True, 'valid': True}, {'source': 'Why Do Coffee Shops Fail', 'pages': [27, 28, 29], 'raw': '[Why Do Coffee Shops Fail, pages 27-29]', 'source_exists': True, 'page_matches': True, 'valid': True}]}
**Retrieved:** [('Why Do Coffee Shops Fail', '[25, 26, 27]'), ('Why Do Coffee Shops Fail', '[27, 28, 29]'), ('Why Do Coffee Shops Fail', '[24, 25]'), ('Why Do Coffee Shops Fail', '[5, 6, 7, 8]'), ('Why Do Coffee Shops Fail', '[22, 23, 24]'), ('Why Do Coffee Shops Fail', '[11, 12, 13, 14, 15]'), ('Why Do Coffee Shops Fail', '[19, 20, 21, 22]'), ('Why Do Coffee Shops Fail', '[1, 2, 3, 4, 5]'), ('Why Do Coffee Shops Fail', '[16, 17, 18, 19]'), ('Why Do Coffee Shops Fail', '[8, 9, 10, 11]')]
**Expected:** Owner burnout is discussed on pages 25-26 of Why Do Coffee Shops Fail (the heading 'Reasons Why Coffee Shops Fail: 12. Coffee shop owner burnout' closes page 25 and the discussion runs on page 26). Page 27 repeats 'Coffee shop owner burnout.' in the summary list, so an answer that also cites page 27 is correct.
**Got:** Owner burnout is discussed in three places in the document:

- **Pages 24–25** — where reason #12, "Coffee shop owner burnout," is introduced: "Being in love with the idea of having a coffee shop and not understanding the work involved can quickly turn your enthusiasm into burnout." [Why Do Coffee Shops Fail, pages 24-25]

- **Pages 25–27** — the main treatment of the topic, covering how often burnout happens, why new owners often experience it within the first two years (difficulty of opening, unexpected growth and growing pains, neglecting personal life, managing employees), its consequences...

### h03 — EQUIVALENT  (page_lookup)
**Q:** On which pages of '7 Costs That Sink Coffee Shops' is 'Employee Giveaways' covered, and what is the core idea?
**Required sources:** [{'source': '7 Costs That Sink Coffee Shops', 'pages': [8, 9, 10, 11]}]
**Recall:** {'applicable': True, 'source_full': True, 'pages_full': True, 'partial': 1.0, 'per_source': [{'source': '7 Costs That Sink Coffee Shops', 'wanted_pages': [8, 9, 10, 11], 'source_hit': True, 'page_hit': True}]}
**MRR@10:** 0.5, **nDCG@10:** 0.6509209298071326
**Judge:** {'relevance': 5, 'groundedness': 3, 'citation_accuracy': 5, 'critical_errors': ['HALLUCINATION'], 'short_rationale': "The claim that employees add extra loyalty-card stamps and the recommendation to switch to a digital loyalty program tied to order history are drawn almost verbatim from the evidence, but the candidate misattributes some of that detail's framing and adds unsupported specificity (e.g., asserting it a", 'flip_rate_relevance': 0.0, 'flip_rate_groundedness': 0.0, 'n_runs': 1, 'escalated': False, 'per_run': [{'relevance': 5, 'groundedness': 3, 'citation_accuracy': 5, 'critical_errors': ['HALLUCINATION'], 'short_rationale': "The claim that employees add extra loyalty-card stamps and the recommendation to switch to a digital loyalty program tied to order history are drawn almost verbatim from the evidence, but the candidate misattributes some of that detail's framing and adds unsupported specificity (e.g., asserting it a"}]}
**Citation validation:** {'n_citations': 2, 'n_source_valid': 2, 'n_page_valid': 2, 'source_accuracy': 1.0, 'page_accuracy': 1.0, 'per_citation': [{'source': '7 Costs That Sink Coffee Shops', 'pages': [8, 9, 10, 11], 'raw': '[7 Costs That Sink Coffee Shops, pages 8-11]', 'source_exists': True, 'page_matches': True, 'valid': True}, {'source': '7 Costs That Sink Coffee Shops', 'pages': [19, 20, 21], 'raw': '[7 Costs That Sink Coffee Shops, pages 19-21]', 'source_exists': True, 'page_matches': True, 'valid': True}]}
**Retrieved:** [('7 Costs That Sink Coffee Shops', '[19, 20, 21]'), ('7 Costs That Sink Coffee Shops', '[8, 9, 10, 11]'), ('7 Costs That Sink Coffee Shops', '[1, 2, 3, 4, 5]'), ('7 Costs That Sink Coffee Shops', '[6, 7, 8]'), ('7 Ways To Run A More Efficient Coffee Shop', '[5, 6]'), ('How to Increase Your Coffee Shop Profits with Loyalty Programs', '[11, 12, 13]'), ('Why Do Coffee Shops Fail', '[5, 6, 7, 8]'), ('Why Do Coffee Shops Fail', '[19, 20, 21, 22]'), ('How to Increase Your Coffee Shop Profits with Loyalty Programs', '[15, 16, 17]'), ('7 Ways To Run A More Efficient Coffee Shop', '[6, 7, 8]')]
**Expected:** Employee Giveaways is covered on pages 8-11 of 7 Costs That Sink Coffee Shops. Core idea: employees giving free drinks/food to friends and family creates a 'double-dipping of losses' — loss of inventory plus loss of sales.
**Got:** **Pages 8–11** of *7 Costs That Sink Coffee Shops* cover "Employee Giveaways" [7 Costs That Sink Coffee Shops, pages 8-11]. It's also listed as one of the seven costs in the summary [7 Costs That Sink Coffee Shops, pages 19-21].

**Core idea:** A limited amount of free coffee for staff is a normal, expected operational cost — complimentary drinks are a positive perk, employees need coffee and milk to experiment with new espresso-based beverages, and dialing in espresso each morning can consume 80–100 grams of coffee [7 Costs That Sink Coffee Shops, pages 8-11]. The real danger is *uncontrolled...

### h05 — EQUIVALENT  (page_lookup)
**Q:** Which pages of '5 KPIs' explain RevPASH and how it is calculated?
**Required sources:** [{'source': '5 KPIs Every Clever Café Manager Should Track', 'pages': [4, 5, 6]}]
**Recall:** {'applicable': True, 'source_full': True, 'pages_full': True, 'partial': 1.0, 'per_source': [{'source': '5 KPIs Every Clever Café Manager Should Track', 'wanted_pages': [4, 5, 6], 'source_hit': True, 'page_hit': True}]}
**MRR@10:** 1.0, **nDCG@10:** 1.0
**Judge:** {'relevance': 4, 'groundedness': 3, 'citation_accuracy': 3, 'critical_errors': ['HALLUCINATION'], 'short_rationale': "The candidate asserts a corrected 'Seat Hours = Number of Seats × Hours Open' formula and labels the literal '/' text as unstated, when the evidence explicitly prints 'Seat Hours = Number of Seats/Hours Open' — silently substituting the operator without flagging the discrepancy misrepresents the sou", 'flip_rate_relevance': 0.0, 'flip_rate_groundedness': 0.0, 'n_runs': 1, 'escalated': False, 'per_run': [{'relevance': 4, 'groundedness': 3, 'citation_accuracy': 3, 'critical_errors': ['HALLUCINATION'], 'short_rationale': "The candidate asserts a corrected 'Seat Hours = Number of Seats × Hours Open' formula and labels the literal '/' text as unstated, when the evidence explicitly prints 'Seat Hours = Number of Seats/Hours Open' — silently substituting the operator without flagging the discrepancy misrepresents the sou"}]}
**Citation validation:** {'n_citations': 2, 'n_source_valid': 2, 'n_page_valid': 2, 'source_accuracy': 1.0, 'page_accuracy': 1.0, 'per_citation': [{'source': '5 KPIs Every Clever Café Manager Should Track', 'pages': [3, 4], 'raw': '[5 KPIs Every Clever Café Manager Should Track, pages 3-4]', 'source_exists': True, 'page_matches': True, 'valid': True}, {'source': '5 KPIs Every Clever Café Manager Should Track', 'pages': [4, 5, 6], 'raw': '[5 KPIs Every Clever Café Manager Should Track, pages 4-6]', 'source_exists': True, 'page_matches': True, 'valid': True}]}
**Retrieved:** [('5 KPIs Every Clever Café Manager Should Track', '[4, 5, 6]'), ('5 KPIs Every Clever Café Manager Should Track', '[3, 4]'), ('High-Level Strategic Roadmap - Transforming a Declining Coffee Shop…', '[2]'), ('Briefing Doc - Opening and Operating a Profitable Coffee Shop', '[1, 2, 3]'), ('Broadway_Cafe_Financial_Model_User_Guide', '[1]'), ('Briefing Doc - Opening and Operating a Profitable Coffee Shop', '[3, 4]'), ('Student “How to Earn an A” One-Page Guide S26', '[2, 3]'), ('Broadway_Cafe_Financial_Model_User_Guide', '[2, 3]'), ('High-Level Strategic Roadmap - Transforming a Declining Coffee Shop…', '[4]'), ('Student “How to Earn an A” One-Page Guide S26', '[3, 4]')]
**Expected:** RevPASH (Revenue Per Available Seat Hour) is introduced on page 4 and the calculation is given on page 5. The document prints 'RevPASH = Total revenue / Seat Hours' and 'Seat Hours = Number of Seats/Hours Open'. That second line is a typo in the source: the worked example on the same page (a 30-seat cafe open 12 hours has 360 seat hours, and 3,000/360 = 8.33) only holds if Seat Hours = Number of Seats x Hours Open. An answer that quotes the document's literal '/' wording and one that gives the corrected 'x' are both acceptable.
**Got:** RevPASH is covered on **pages 3–6** of the document:

- **Pages 3–4** introduce the metric: Revenue Per Available Seat Hour is described as a relatively new KPI developed by Dr Sheryl Kimes of Cornell University School, important because it factors in time — analogous to the hotel industry's RevPAR (revenue per available room) — and because it combines time, capacity, and average check size into a fuller picture of the business than any of those metrics alone [5 KPIs Every Clever Café Manager Should Track, pages 3-4].

- **Pages 4–6** give the calculation and how to improve it: RevPASH = Total...

### h06 — PARTIAL  (page_lookup)
**Q:** On what page does '5 KPIs' first explicitly list 'Here are 5 KPIs every Clever Café manager should track'?
**Required sources:** [{'source': '5 KPIs Every Clever Café Manager Should Track', 'pages': [2]}]
**Recall:** {'applicable': True, 'source_full': True, 'pages_full': True, 'partial': 1.0, 'per_source': [{'source': '5 KPIs Every Clever Café Manager Should Track', 'wanted_pages': [2], 'source_hit': True, 'page_hit': True}]}
**MRR@10:** 1.0, **nDCG@10:** 1.0
**Judge:** {'relevance': 3, 'groundedness': 4, 'citation_accuracy': 4, 'critical_errors': ['CITATION_WRONG'], 'short_rationale': "The candidate cites the merged chunk range 'pages 1-3' as its source rather than the specific page 2 the reference answer identifies, and explicitly admits it cannot pin down the exact page, so its citation does not correspond to the correct single page.", 'flip_rate_relevance': 0.0, 'flip_rate_groundedness': 0.0, 'n_runs': 1, 'escalated': True, 'per_run': [{'relevance': 3, 'groundedness': 4, 'citation_accuracy': 2, 'critical_errors': ['CITATION_WRONG'], 'short_rationale': "The candidate cites the merged chunk range 'pages 1-3' as its source rather than the specific page 2 the reference answer identifies, and explicitly admits it cannot pin down the exact page, so its citation does not correspond to the correct single page."}]}
**Citation validation:** {'n_citations': 1, 'n_source_valid': 1, 'n_page_valid': 1, 'source_accuracy': 1.0, 'page_accuracy': 1.0, 'per_citation': [{'source': '5 KPIs Every Clever Café Manager Should Track', 'pages': [1, 2, 3], 'raw': '[5 KPIs Every Clever Café Manager Should Track, pages 1-3]', 'source_exists': True, 'page_matches': True, 'valid': True}]}
**Retrieved:** [('5 KPIs Every Clever Café Manager Should Track', '[1, 2, 3]'), ('5 KPIs Every Clever Café Manager Should Track', '[6, 7]'), ('Briefing Doc - Opening and Operating a Profitable Coffee Shop', '[3, 4]'), ('7 Costs That Sink Coffee Shops', '[17, 18, 19]'), ('Broadway_Cafe_Financial_Model_User_Guide', '[2, 3]'), ('Top Metrics to Track to Measure Your Coffee Shop Franchise’s Performance', '[3, 4, 5, 6]'), ('Top Metrics to Track to Measure Your Coffee Shop Franchise’s Performance', '[1, 2, 3]'), ('Broadway_Cafe_Financial_Model_User_Guide', '[1]'), ('Briefing Doc - Opening and Operating a Profitable Coffee Shop', '[1, 2, 3]'), ('7 Costs That Sink Coffee Shops', '[8, 9, 10, 11]')]
**Expected:** The explicit '5 KPIs' framing appears on page 2 of the document, immediately followed by KPI #1 Employee Retention Rate.
**Got:** The line "Here are 5 KPIs every Clever Café manager should track:" appears in the opening section of the document, in the chunk covering [5 KPIs Every Clever Café Manager Should Track, pages 1-3] — it comes right after the introductory discussion of KPIs and immediately before the "1. Employee Retention Rate" heading [5 KPIs Every Clever Café Manager Should Track, pages 1-3].

The context does not break that section down page by page, so I can't tell you the exact single page number. Given it directly follows the article's intro, it is almost certainly on page 1 or 2, but the provided context ...

### h07 — EQUIVALENT  (synthesis)
**Q:** Compare how the 'Briefing Doc - Opening and Operating a Profitable Coffee Shop' and 'Calculating Your Break Even Point' present the break-even calculation. What's the same and what's different?
**Required sources:** [{'source': 'Briefing Doc - Opening and Operating a Profitable Coffee Shop', 'pages': [4, 5]}, {'source': 'Calculating Your Break Even Point', 'pages': [2, 3, 4, 5]}]
**Recall:** {'applicable': True, 'source_full': True, 'pages_full': True, 'partial': 1.0, 'per_source': [{'source': 'Briefing Doc - Opening and Operating a Profitable Coffee Shop', 'wanted_pages': [4, 5], 'source_hit': True, 'page_hit': True}, {'source': 'Calculating Your Break Even Point', 'wanted_pages': [2, 3, 4, 5], 'source_hit': True, 'page_hit': True}]}
**MRR@10:** 0.5, **nDCG@10:** 0.6871475159848289
**Judge:** {'relevance': 5, 'groundedness': 4, 'citation_accuracy': 4, 'critical_errors': ['CITATION_WRONG'], 'short_rationale': "Most citations map correctly to evidence content, but the claim that the source 'recommends including' startup costs is an overstatement (the source explicitly says 'you will have to determine what makes more sense for you,' leaving it open rather than recommending inclusion).", 'flip_rate_relevance': 0.0, 'flip_rate_groundedness': 0.0, 'n_runs': 1, 'escalated': False, 'per_run': [{'relevance': 5, 'groundedness': 4, 'citation_accuracy': 4, 'critical_errors': ['CITATION_WRONG'], 'short_rationale': "Most citations map correctly to evidence content, but the claim that the source 'recommends including' startup costs is an overstatement (the source explicitly says 'you will have to determine what makes more sense for you,' leaving it open rather than recommending inclusion)."}]}
**Citation validation:** {'n_citations': 7, 'n_source_valid': 6, 'n_page_valid': 6, 'source_accuracy': 0.8571428571428571, 'page_accuracy': 0.8571428571428571, 'per_citation': [{'source': 'Briefing Doc - Opening and Operating a Profitable Coffee Shop', 'pages': [3], 'raw': '[Briefing Doc - Opening and Operating a Profitable Coffee Shop, page 3]', 'source_exists': True, 'page_matches': True, 'valid': True}, {'source': 'Calculating Your Break Even Point', 'pages': [1, 2, 3], 'raw': '[Calculating Your Break Even Point, pages 1-3]', 'source_exists': True, 'page_matches': True, 'valid': True}, {'source': 'Briefing Doc', 'pages': [4, 5], 'raw': '[Briefing Doc, pages 4-5]', 'source_exists': True, 'page_matches': True, 'valid': True}, {'source': 'Calculating Your Break Even Point', 'pages': [4, 5], 'raw': '[Calculating Your Break Even Point, pages 4-5]', 'source_exists': True, 'page_matches': True, 'valid': True}, {'source': 'Briefing Doc, pages 4-5 and', 'pages': [6, 7], 'raw': '[Briefing Doc, pages 4-5 and pages 6-7]', 'source_exists': False, 'page_matches': False, 'valid': False}, {'source': 'Briefing Doc', 'pages': [3], 'raw': '[Briefing Doc, page 3]', 'source_exists': True, 'page_matches': True, 'valid': True}, {'source': 'Briefing Doc', 'pages': [1, 2, 3], 'raw': '[Briefing Doc, pages 1-3]', 'source_exists': True, 'page_matches': True, 'valid': True}]}
**Retrieved:** [('Briefing Doc - Opening and Operating a Profitable Coffee Shop', '[1, 2, 3]'), ('Briefing Doc - Opening and Operating a Profitable Coffee Shop', '[4, 5]'), ('Calculating Your Break Even Point', '[1, 2, 3]'), ('Briefing Doc - Opening and Operating a Profitable Coffee Shop', '[6, 7]'), ('Briefing Doc - Opening and Operating a Profitable Coffee Shop', '[3]'), ('Why Do Coffee Shops Fail', '[24, 25]'), ('Calculating Your Break Even Point', '[4, 5]'), ('Broadway_Cafe_Financial_Model_Template S26', '[4, 5, 6, 7, 8, 9, 10]'), ('Broadway_Cafe_Financial_Model_Template S26', '[1, 2, 3]'), ('Why Do Coffee Shops Fail', '[8, 9, 10, 11]')]
**Expected:** Both define break-even as the sales level where total costs are covered. The Briefing Doc gives a simple formula: Fixed Costs / Gross Margin %, with example $22,000 / 0.85 = $26,000. Calculating Your Break Even Point gives a more detailed multi-step method: amortize startup costs, sum monthly fixed and variable costs, then Fixed Costs / Sales Margin where Sales Margin = Gross Sales Revenue − Variable Costs. Worked example uses $7,200 fixed + $2,800 variable = $10,000 monthly cost vs ~$522/day revenue.
**Got:** Both documents cover the same concept, but at very different levels of resolution — the Briefing Doc is a condensed summary, while "Calculating Your Break Even Point" is the procedural source it summarizes.

## What's the same

- **Definition.** Both define the break-even point identically: the moment total costs equal revenue, below which you aren't profitable and above which you are, and the point at which operations have covered both fixed and variable costs [Briefing Doc - Opening and Operating a Profitable Coffee Shop, page 3][Calculating Your Break Even Point, pages 1-3].
- **The fixed-c...
