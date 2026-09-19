# Eval Results

======================================================================
RESULTS  (20 questions, 936.6s)
======================================================================
Retrieval recall@10:    100.0%  (20/20)
Answer correctness:     95.0%  (19 EQUIVALENT)
  + partial credit:    100.0%  (+ 1 PARTIAL)
  different:           0
  errors:              0
======================================================================

## Per-question

| ID | Recall | Verdict | Question |
|---|---|---|---|
| q01 | ✓ | EQUIVALENT | What are the main reasons coffee shops fail according to the materials? |
| q02 | ✓ | EQUIVALENT | What are the seven costs that sink coffee shops? |
| q03 | ✓ | PARTIAL | What are five KPIs every coffee shop manager should track? |
| q04 | ✓ | EQUIVALENT | List ways to run a more efficient coffee shop. |
| q05 | ✓ | EQUIVALENT | How do you calculate the cost of selling 100 coffees? |
| q06 | ✓ | EQUIVALENT | How do you calculate a coffee shop's break-even point? |
| q07 | ✓ | EQUIVALENT | What was the 2023 baseline annual revenue for Broadway Cafe? |
| q08 | ✓ | EQUIVALENT | What is the projected COGS percentage for Broadway Cafe in 2026? |
| q09 | ✓ | EQUIVALENT | What is the total funding request in the Broadway Cafe financial model? |
| q10 | ✓ | EQUIVALENT | How can loyalty programs increase coffee shop profits? |
| q11 | ✓ | EQUIVALENT | How should a coffee shop promote and market itself? |
| q12 | ✓ | EQUIVALENT | How can a coffee shop revamp its menu to increase profits? |
| q13 | ✓ | EQUIVALENT | How can a coffee shop beat its competition? |
| q14 | ✓ | EQUIVALENT | What metrics should a coffee shop franchise track to measure performance? |
| q15 | ✓ | EQUIVALENT | How can a coffee shop use customer data to understand its customers? |
| q16 | ✓ | EQUIVALENT | What is When I Work software used for? |
| q17 | ✓ | EQUIVALENT | What is the high-level strategic roadmap for transforming a declining coffee sho |
| q18 | ✓ | EQUIVALENT | What does the MIS 311 team accountability checklist cover? |
| q19 | ✓ | EQUIVALENT | What are the business plan assumptions for the Broadway Cafe project? |
| q20 | ✓ | EQUIVALENT | How will finalist team presentations be judged in the capstone? |

## Failures (DIFFERENT or PARTIAL)

### q03 — PARTIAL
**Q:** What are five KPIs every coffee shop manager should track?
**Expected source:** `5 KPIs Every Clever Café Manager Should Track` (recall hit: True)
**Retrieved sources:** ['5 KPIs Every Clever Café Manager Should Track', 'Briefing Doc - Opening and Operating a Profitable Coffee Shop', 'Top Metrics to Track to Measure Your Coffee Shop Franchise’s Performance', 'Briefing Doc - Opening and Operating a Profitable Coffee Shop', 'High-Level Strategic Roadmap - Transforming a Declining Coffee Shop…', 'Why Do Coffee Shops Fail', 'Why Do Coffee Shops Fail', '7 Ways To Run A More Efficient Coffee Shop', 'Briefing Doc - Opening and Operating a Profitable Coffee Shop', '7 Costs That Sink Coffee Shops']
**Expected:** The five KPIs are: (1) Employee Retention Rate, (2) RevPASH (Revenue Per Available Seat Hour, calculated as Total Revenue ÷ Seat Hours), (3) Labour Cost Percentage (also called Sales per Labour Hour), (4) Revenue per Employee (sales per head / average ticket size), and (5) a metric related to seating efficiency / how quickly patrons are seated (table turn).
**Got:** Based on the document "5 KPIs Every Clever Café Manager Should Track," here are the five KPIs every café manager should track:

1. **Employee Retention Rate** — The percentage of employees who remain with the business over a given period. High turnover is costly due to hiring and training expenses, and poor staff can damage the customer experience. (pages 1–2)

2. **RevPASH (Revenue Per Available Seat Hour)** — Measures how efficiently each seat generates revenue by incorporating time and capacity alongside average check size. Calculated as: Total Revenue ÷ (Number of Seats × Hours Open). (pag...
