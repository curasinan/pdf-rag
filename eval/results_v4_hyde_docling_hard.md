# Eval Results — HARD

========================================================================
RESULTS — HARD eval  (25 questions, 1670.3s)
========================================================================
Retrieval recall@10 (source):  100.0%  (21/21)
Retrieval recall@10 (pages):    90.5%  (19/21)
Answer correctness (EQUIVALENT):    68.0%  (17/25)
  + partial credit:                 92.0%  (+ 6 PARTIAL)
  different:                       2
  errors:                          0
========================================================================

## Per-question

| ID | Type | Recall src/pg | Verdict | Question |
|---|---|---|---|---|
| h01 | page_lookup | ✓ / ✗ | PARTIAL | What is described as KPI #5 in the 5 KPIs document, and on which page is it defi |
| h02 | page_lookup | ✓ / ✓ | PARTIAL | On what pages does the Why Do Coffee Shops Fail document discuss owner burnout? |
| h03 | page_lookup | ✓ / ✓ | EQUIVALENT | On which pages of '7 Costs That Sink Coffee Shops' is 'Employee Giveaways' cover |
| h04 | page_lookup | ✓ / ✓ | DIFFERENT | Which page of the Calculating Your Break Even Point document contains the worked |
| h05 | page_lookup | ✓ / ✓ | PARTIAL | Which pages of '5 KPIs' explain RevPASH and how it is calculated? |
| h06 | page_lookup | ✓ / ✓ | DIFFERENT | On what page does '5 KPIs' first explicitly list 'Here are 5 KPIs every Clever C |
| h07 | synthesis | ✓ / ✓ | EQUIVALENT | Compare how the 'Briefing Doc - Opening and Operating a Profitable Coffee Shop'  |
| h08 | synthesis | ✓ / ✓ | PARTIAL | How do the '5 KPIs Every Clever Café Manager Should Track' and 'Top Metrics to T |
| h09 | synthesis | ✓ / ✓ | EQUIVALENT | Which cost categories appear in BOTH '7 Costs That Sink Coffee Shops' and 'How t |
| h10 | synthesis | ✓ / ✓ | EQUIVALENT | How does the High-Level Strategic Roadmap relate to the Business Plan Assumption |
| h11 | synthesis | ✓ / ✓ | EQUIVALENT | Both 'How to Increase Your Coffee Shop Profits with Loyalty Programs' and 'How T |
| h12 | numeric | ✓ / ✓ | EQUIVALENT | What is the 2023 baseline annual revenue figure for Broadway Cafe in the financi |
| h13 | numeric | ✓ / ✓ | EQUIVALENT | What is the projected COGS percentage for Broadway Cafe in 2026, and what does i |
| h14 | numeric | ✓ / ✓ | EQUIVALENT | In the 'How to Determine the Cost of Selling 100 Coffees' document, what is the  |
| h15 | numeric | ✓ / ✓ | EQUIVALENT | In the worked example in 'Calculating Your Break Even Point', what are the month |
| h16 | numeric | ✓ / ✓ | EQUIVALENT | How much funding does the Broadway Cafe financial model request in total? |
| h17 | qa | ✓ / ✗ | PARTIAL | What does '7 Costs That Sink Coffee Shops' mean by 'The Cost of Time'? |
| h18 | qa | ✓ / ✓ | EQUIVALENT | What guidance does 'How to Revamp Your Coffee Shop Menu' give about menu length? |
| h19 | qa | ✓ / ✓ | EQUIVALENT | What are the tiebreaker rules in the Finalist Team Presentation Judging Rubric? |
| h20 | qa | ✓ / ✓ | EQUIVALENT | What does the MIS 311 Team Accountability Checklist recommend for managing inter |
| h21 | qa | ✓ / ✓ | PARTIAL | What KPIs does the High-Level Strategic Roadmap propose for the modernization ph |
| h22 | negative | — / — | EQUIVALENT | Do any of the materials discuss quantum computing applications for coffee shops? |
| h23 | negative | — / — | EQUIVALENT | Is there any discussion of NFTs or cryptocurrency-based loyalty tokens in the ma |
| h24 | negative | — / — | EQUIVALENT | Do any of the documents cover pizza delivery operations? |
| h25 | negative | — / — | EQUIVALENT | Do the materials reference video game design principles applied to café customer |

## Failures (DIFFERENT, PARTIAL, or ERROR)

### h01 — PARTIAL  (page_lookup)
**Q:** What is described as KPI #5 in the 5 KPIs document, and on which page is it defined?
**Required sources:** [{'source': '5 KPIs Every Clever Café Manager Should Track', 'pages': [8]}]
**Recall:** {'applicable': True, 'source_full': True, 'pages_full': False, 'partial': 1.0, 'per_source': [{'source': '5 KPIs Every Clever Café Manager Should Track', 'wanted_pages': [8], 'source_hit': True, 'page_hit': False}]}
**Retrieved:** [('5 KPIs Every Clever Café Manager Should Track', '[1, 2, 3]'), ('5 KPIs Every Clever Café Manager Should Track', '[4, 5, 6]'), ('High-Level Strategic Roadmap - Transforming a Declining Coffee Shop…', '[2]'), ('Briefing Doc - Opening and Operating a Profitable Coffee Shop', '[3, 4]'), ('High-Level Strategic Roadmap - Transforming a Declining Coffee Shop…', '[4]'), ('Broadway_Cafe_Financial_Model_Template S26', '[9, 10, 11, 12, 13, 14]'), ('Briefing Doc - Opening and Operating a Profitable Coffee Shop', '[6, 7]'), ('Appendix X AI Use Disclosure Team-Level — Manager Judgment Required', '[1]'), ('Broadway_Cafe_Financial_Model_User_Guide', '[2, 3]'), ('Broadway_Cafe_Financial_Model_Template S26', '[1, 2, 3]')]
**Expected:** KPI #5 is Table Turn Time, defined on page 8 of the 5 KPIs document.
**Got:** Based on the provided context, **KPI #5 is not fully defined** in the excerpts given. However, there is a reference to it on **pages 4–5** in the RevPASH section, which states:

> "you could examine how quickly patrons are seated (see KPI number 5 in our article)"

This strongly suggests that **KPI #5 relates to seating speed or table turnover** (how quickly patrons are seated), but the actual section defining KPI #5 in detail was not included in the context provided to me. The document covers pages 1–6, and while KPI #1 (Employee Retention Rate) and RevPASH are defined in the excerpts, the de...

### h02 — PARTIAL  (page_lookup)
**Q:** On what pages does the Why Do Coffee Shops Fail document discuss owner burnout?
**Required sources:** [{'source': 'Why Do Coffee Shops Fail', 'pages': [25, 26]}]
**Recall:** {'applicable': True, 'source_full': True, 'pages_full': True, 'partial': 1.0, 'per_source': [{'source': 'Why Do Coffee Shops Fail', 'wanted_pages': [25, 26], 'source_hit': True, 'page_hit': True}]}
**Retrieved:** [('Why Do Coffee Shops Fail', '[25, 26, 27]'), ('Why Do Coffee Shops Fail', '[27, 28, 29]'), ('Briefing Doc - Opening and Operating a Profitable Coffee Shop', '[1, 2, 3]'), ('Briefing Doc - Opening and Operating a Profitable Coffee Shop', '[3, 4]'), ('7 Costs That Sink Coffee Shops', '[1, 2, 3, 4, 5]'), ('7 Costs That Sink Coffee Shops', '[14, 15, 16, 17]'), ('How to Promote and Market Your Coffee Shop', '[1, 2, 3]'), ('How to Beat Your Coffee Shop Competition', '[7, 8, 9, 10]'), ('How to Beat Your Coffee Shop Competition', '[13, 14, 15, 16, 18]'), ('How to improve sales and profitabiity for your coffe shop', '[11, 12]')]
**Expected:** Owner burnout is discussed on pages 25-26 of Why Do Coffee Shops Fail.
**Got:** The "Why Do Coffee Shops Fail" document discusses owner burnout on **pages 25–27**. This section covers how burnout can occur within the first two years, its common causes (difficulty of opening, unexpected growth, managing employees, neglecting personal life), its consequences (poor service, laggard sales, business closure), and strategies to avoid it (hiring right, delegating, resting, budgeting, planning).

### h04 — DIFFERENT  (page_lookup)
**Q:** Which page of the Calculating Your Break Even Point document contains the worked example with concrete numbers?
**Required sources:** [{'source': 'Calculating Your Break Even Point', 'pages': [2, 3]}]
**Recall:** {'applicable': True, 'source_full': True, 'pages_full': True, 'partial': 1.0, 'per_source': [{'source': 'Calculating Your Break Even Point', 'wanted_pages': [2, 3], 'source_hit': True, 'page_hit': True}]}
**Retrieved:** [('Briefing Doc - Opening and Operating a Profitable Coffee Shop', '[4, 5]'), ('Briefing Doc - Opening and Operating a Profitable Coffee Shop', '[1, 2, 3]'), ('Calculating Your Break Even Point', '[1, 2, 3]'), ('Calculating Your Break Even Point', '[4, 5]'), ('High-Level Strategic Roadmap - Transforming a Declining Coffee Shop…', '[3]'), ('Broadway_Cafe_Financial_Model_User_Guide', '[2, 3]'), ('Broadway_Cafe_Financial_Model_User_Guide', '[1]'), ('Broadway_Cafe_Financial_Model_Template S26', '[4, 5, 6, 7, 8, 9, 10]'), ('Broadway_Cafe_Financial_Model_Template S26', '[1, 2, 3]'), ('High-Level Strategic Roadmap - Transforming a Declining Coffee Shop…', '[4]')]
**Expected:** Pages 2-3 contain the worked example: $7,200 monthly fixed costs (rent $2,000, insurance $300, loan $350, salary $4,200), $2,800 variable costs, $522 daily revenue.
**Got:** The worked example with concrete numbers appears on **pages 4–5** of the *Calculating Your Break Even Point* document. That section includes:

- **Cost breakdown for 1 Americano**: $0.50 (coffee) + $0.27 (cup, lid, & sleeve) = **$0.77 total cost**
- **Sale price**: $2.75
- **Margin**: $1.98

It also walks through the step-by-step break-even calculation method (adding up fixed, variable, and monthly startup costs, then dividing fixed costs by the sales margin).

Pages 1–3 of the same document also contain a **startup cost scenario** (e.g., $21,800 total startup costs, $10,000 borrowed at $350/m...

### h05 — PARTIAL  (page_lookup)
**Q:** Which pages of '5 KPIs' explain RevPASH and how it is calculated?
**Required sources:** [{'source': '5 KPIs Every Clever Café Manager Should Track', 'pages': [4, 5]}]
**Recall:** {'applicable': True, 'source_full': True, 'pages_full': True, 'partial': 1.0, 'per_source': [{'source': '5 KPIs Every Clever Café Manager Should Track', 'wanted_pages': [4, 5], 'source_hit': True, 'page_hit': True}]}
**Retrieved:** [('5 KPIs Every Clever Café Manager Should Track', '[4, 5, 6]'), ('5 KPIs Every Clever Café Manager Should Track', '[3, 4]'), ('High-Level Strategic Roadmap - Transforming a Declining Coffee Shop…', '[2]'), ('Briefing Doc - Opening and Operating a Profitable Coffee Shop', '[1, 2, 3]'), ('Broadway_Cafe_Financial_Model_User_Guide', '[1]'), ('Briefing Doc - Opening and Operating a Profitable Coffee Shop', '[3, 4]'), ('Student “How to Earn an A” One-Page Guide S26', '[2, 3]'), ('High-Level Strategic Roadmap - Transforming a Declining Coffee Shop…', '[3]'), ('Broadway_Cafe_Financial_Model_User_Guide', '[2, 3]'), ('Student “How to Earn an A” One-Page Guide S26', '[3, 4]')]
**Expected:** RevPASH (Revenue Per Available Seat Hour) is explained on pages 4-5. Calculated as Total Revenue / Seat Hours, where Seat Hours = Number of Seats × Hours Open.
**Got:** RevPASH (Revenue Per Available Seat Hour) is explained and its calculation is covered on **pages 3–6** of *5 KPIs Every Clever Café Manager Should Track*:

- **Pages 3–4** introduce RevPASH as a KPI, explain its origin (developed by Dr Sheryl Kimes of Cornell University), and describe why it is useful — it incorporates time, capacity, and average check size into a single metric.
- **Pages 4–6** provide the calculation formula and a worked example:

  **RevPASH = Total Revenue ÷ Seat Hours**
  where Seat Hours = Number of Seats × Hours Open.

  Example: a 30-seat café open 12 hours has 360 seat...

### h06 — DIFFERENT  (page_lookup)
**Q:** On what page does '5 KPIs' first explicitly list 'Here are 5 KPIs every Clever Café manager should track'?
**Required sources:** [{'source': '5 KPIs Every Clever Café Manager Should Track', 'pages': [2]}]
**Recall:** {'applicable': True, 'source_full': True, 'pages_full': True, 'partial': 1.0, 'per_source': [{'source': '5 KPIs Every Clever Café Manager Should Track', 'wanted_pages': [2], 'source_hit': True, 'page_hit': True}]}
**Retrieved:** [('5 KPIs Every Clever Café Manager Should Track', '[1, 2, 3]'), ('5 KPIs Every Clever Café Manager Should Track', '[6, 7]'), ('Briefing Doc - Opening and Operating a Profitable Coffee Shop', '[3, 4]'), ('7 Ways To Run A More Efficient Coffee Shop', '[9, 10]'), ('7 Costs That Sink Coffee Shops', '[17, 18, 19]'), ('Broadway_Cafe_Financial_Model_User_Guide', '[2, 3]'), ('7 Ways To Run A More Efficient Coffee Shop', '[1, 2]'), ('Briefing Doc - Opening and Operating a Profitable Coffee Shop', '[6, 7]'), ('Broadway_Cafe_Financial_Model_User_Guide', '[1]'), ('7 Costs That Sink Coffee Shops', '[8, 9, 10, 11]')]
**Expected:** The explicit '5 KPIs' framing appears on page 2 of the document, immediately followed by KPI #1 Employee Retention Rate.
**Got:** The phrase "Here are 5 KPIs every Clever Café manager should track:" first appears on **pages 1–2** of *5 KPIs Every Clever Café Manager Should Track* (the chunk covering pages [1, 2, 3]).

### h08 — PARTIAL  (synthesis)
**Q:** How do the '5 KPIs Every Clever Café Manager Should Track' and 'Top Metrics to Track to Measure Your Coffee Shop Franchise's Performance' differ in what they recommend tracking?
**Required sources:** [{'source': '5 KPIs Every Clever Café Manager Should Track', 'pages': [2, 3, 4, 5, 6, 7, 8]}, {'source': 'Top Metrics to Track to Measure Your Coffee Shop Franchise’s Performance', 'pages': [1, 2, 3, 4, 5]}]
**Recall:** {'applicable': True, 'source_full': True, 'pages_full': True, 'partial': 1.0, 'per_source': [{'source': '5 KPIs Every Clever Café Manager Should Track', 'wanted_pages': [2, 3, 4, 5, 6, 7, 8], 'source_hit': True, 'page_hit': True}, {'source': 'Top Metrics to Track to Measure Your Coffee Shop Franchise’s Performance', 'wanted_pages': [1, 2, 3, 4, 5], 'source_hit': True, 'page_hit': True}]}
**Retrieved:** [('5 KPIs Every Clever Café Manager Should Track', '[1, 2, 3]'), ('Top Metrics to Track to Measure Your Coffee Shop Franchise’s Performance', '[1, 2, 3]'), ('Briefing Doc - Opening and Operating a Profitable Coffee Shop', '[3, 4]'), ('Top Metrics to Track to Measure Your Coffee Shop Franchise’s Performance', '[3, 4, 5, 6]'), ('Briefing Doc - Opening and Operating a Profitable Coffee Shop', '[6, 7]'), ('5 KPIs Every Clever Café Manager Should Track', '[6, 7]'), ('7 Ways To Run A More Efficient Coffee Shop', '[9, 10]'), ('7 Costs That Sink Coffee Shops', '[17, 18, 19]'), ('7 Ways To Run A More Efficient Coffee Shop', '[1, 2]'), ('7 Costs That Sink Coffee Shops', '[1, 2, 3, 4, 5]')]
**Expected:** 5 KPIs is operations-focused for a single café manager: Employee Retention, RevPASH, Labour Cost %, Revenue per Employee, Table Turn Time. Top Metrics (PJ's Coffee) is franchise-focused on financial KPIs: COGs, Labor Percentages, Top-Line Sales, plus customer metrics like Loyalty System Participation. The 5 KPIs piece emphasizes seat-hour efficiency and table turns; the franchise piece emphasizes inventory-control and labor-management systems.
**Got:** ## Comparison of Recommended KPIs

The two documents take notably different approaches:

**"5 KPIs Every Clever Café Manager Should Track"** focuses on **staff-centric and operational metrics** aimed at independent café managers:

1. **Employee Retention Rate** — percentage of staff who stay over a given period, emphasizing the cost of turnover and hiring the wrong people (pages 1–2)
2. **Labour Cost Percentage (SpLH)** — sales made during a period divided by total labour cost, highlighting that even a 1% difference can mean profit vs. loss (pages 6–7)
3. **Revenue by Employee** — also called ...

### h17 — PARTIAL  (qa)
**Q:** What does '7 Costs That Sink Coffee Shops' mean by 'The Cost of Time'?
**Required sources:** [{'source': '7 Costs That Sink Coffee Shops', 'pages': [15, 16]}]
**Recall:** {'applicable': True, 'source_full': True, 'pages_full': False, 'partial': 1.0, 'per_source': [{'source': '7 Costs That Sink Coffee Shops', 'wanted_pages': [15, 16], 'source_hit': True, 'page_hit': False}]}
**Retrieved:** [('7 Costs That Sink Coffee Shops', '[19, 20, 21]'), ('7 Costs That Sink Coffee Shops', '[1, 2, 3, 4, 5]'), ('Why Do Coffee Shops Fail', '[5, 6, 7, 8]'), ('Why Do Coffee Shops Fail', '[1, 2, 3, 4, 5]'), ('Briefing Doc - Opening and Operating a Profitable Coffee Shop', '[6, 7]'), ('Calculating Your Break Even Point', '[2, 3, 4]'), ('Briefing Doc - Opening and Operating a Profitable Coffee Shop', '[1, 2, 3]'), ('How to improve sales and profitabiity for your coffe shop', '[4, 5, 6]'), ('How to improve sales and profitabiity for your coffe shop', '[6, 7]'), ('Calculating Your Break Even Point', '[1, 2, 3]')]
**Expected:** The Cost of Time refers to time the owner loses to issues with customers, vendors, and employees. This consumed time leads to inefficiency, poor decisions, and ultimately significant financial losses, even though it doesn't appear as a line-item cost.
**Got:** The document lists "The cost of time" as one of the seven business-threatening costs on pages 19–21 in the summary section. However, the detailed explanation for that specific cost is **not included in the provided context**. The context only contains the full discussion of "Over-Scheduling Baristas" (pages 1–5) and the summary list, but the section elaborating on "The Cost of Time" (likely found on intermediate pages) was not retrieved.

Based on the broader themes across the documents, it likely refers to the hidden cost of an owner's own time — time spent on inefficient tasks, poor systems,...

### h21 — PARTIAL  (qa)
**Q:** What KPIs does the High-Level Strategic Roadmap propose for the modernization phases?
**Required sources:** [{'source': 'High-Level Strategic Roadmap - Transforming a Declining Coffee Shop…', 'pages': [3, 4]}]
**Recall:** {'applicable': True, 'source_full': True, 'pages_full': True, 'partial': 1.0, 'per_source': [{'source': 'High-Level Strategic Roadmap - Transforming a Declining Coffee Shop…', 'wanted_pages': [3, 4], 'source_hit': True, 'page_hit': True}]}
**Retrieved:** [('High-Level Strategic Roadmap - Transforming a Declining Coffee Shop…', '[1]'), ('Student “How to Earn an A” One-Page Guide S26', '[3, 4]'), ('High-Level Strategic Roadmap - Transforming a Declining Coffee Shop…', '[4]'), ('Broadway_Cafe_Financial_Model_Template S26', '[9, 10, 11, 12, 13, 14]'), ('Broadway_Cafe_Financial_Model_User_Guide', '[3]'), ('Broadway_Cafe_Financial_Model_User_Guide', '[2, 3]'), ('Business Plan Assumptions S26', '[1, 2]'), ('Broadway_Cafe_Financial_Model_Template S26', '[1, 2, 3]'), ('Appendix X AI Use Disclosure Team-Level — Manager Judgment Required', '[1]'), ('Student “How to Earn an A” One-Page Guide S26', '[2, 3]')]
**Expected:** Inventory Turnover Ratio (reduces excess stock and waste), Order Fulfillment Speed (online and in-store service times), and Digital Adoption Rate (percentage of transactions via mobile and POS) — among others tied to phased modernization.
**Got:** Based on the **High-Level Strategic Roadmap** (page 4), the proposed KPIs are tied to Critical Success Factors (CSFs):

| CSF | KPI |
|---|---|
| **Digital Adoption** | 80% of transactions via mobile & POS |
| **Customer Retention** | 50% growth in loyalty program members |
| **Sales Increase** | 20% higher foot traffic in Year 1 |
| **Cost Reduction** | 10% decrease in operational waste |
| **Profitability** | 30% increase within three years |

These five KPIs map directly to the roadmap's overarching goal of transforming the declining coffee shop into a profitable, technology-driven enterpri...
