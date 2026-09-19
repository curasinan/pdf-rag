# Eval Results

======================================================================
RESULTS  (20 questions, 973.9s)
======================================================================
Retrieval recall@10:     95.0%  (19/20)
Answer correctness:     65.0%  (13 EQUIVALENT)
  + partial credit:    100.0%  (+ 7 PARTIAL)
  different:           0
  errors:              0
======================================================================

## Per-question

| ID | Recall | Verdict | Question |
|---|---|---|---|
| q01 | ✓ | EQUIVALENT | What are the main reasons coffee shops fail according to the materials? |
| q02 | ✓ | PARTIAL | What are the seven costs that sink coffee shops? |
| q03 | ✗ | PARTIAL | What are five KPIs every coffee shop manager should track? |
| q04 | ✓ | EQUIVALENT | List ways to run a more efficient coffee shop. |
| q05 | ✓ | PARTIAL | How do you calculate the cost of selling 100 coffees? |
| q06 | ✓ | PARTIAL | How do you calculate a coffee shop's break-even point? |
| q07 | ✓ | EQUIVALENT | What was the 2023 baseline annual revenue for Broadway Cafe? |
| q08 | ✓ | EQUIVALENT | What is the projected COGS percentage for Broadway Cafe in 2026? |
| q09 | ✓ | EQUIVALENT | What is the total funding request in the Broadway Cafe financial model? |
| q10 | ✓ | EQUIVALENT | How can loyalty programs increase coffee shop profits? |
| q11 | ✓ | EQUIVALENT | How should a coffee shop promote and market itself? |
| q12 | ✓ | PARTIAL | How can a coffee shop revamp its menu to increase profits? |
| q13 | ✓ | EQUIVALENT | How can a coffee shop beat its competition? |
| q14 | ✓ | PARTIAL | What metrics should a coffee shop franchise track to measure performance? |
| q15 | ✓ | EQUIVALENT | How can a coffee shop use customer data to understand its customers? |
| q16 | ✓ | EQUIVALENT | What is When I Work software used for? |
| q17 | ✓ | EQUIVALENT | What is the high-level strategic roadmap for transforming a declining coffee sho |
| q18 | ✓ | EQUIVALENT | What does the MIS 311 team accountability checklist cover? |
| q19 | ✓ | EQUIVALENT | What are the business plan assumptions for the Broadway Cafe project? |
| q20 | ✓ | PARTIAL | How will finalist team presentations be judged in the capstone? |

## Failures (DIFFERENT or PARTIAL)

### q02 — PARTIAL
**Q:** What are the seven costs that sink coffee shops?
**Expected source:** `7 Costs That Sink Coffee Shops` (recall hit: True)
**Retrieved sources:** ['7 Costs That Sink Coffee Shops', '7 Costs That Sink Coffee Shops', 'Why Do Coffee Shops Fail', '7 Costs That Sink Coffee Shops', 'Briefing Doc - Opening and Operating a Profitable Coffee Shop', 'How to improve sales and profitabiity for your coffe shop', 'Calculating Your Break Even Point', 'Why Do Coffee Shops Fail', 'Why Do Coffee Shops Fail', 'Briefing Doc - Opening and Operating a Profitable Coffee Shop']
**Expected:** The seven major cost categories that sink coffee shops, including rent/lease costs, equipment costs, labor, COGS (cost of goods sold), utilities, marketing/advertising, and waste/spoilage.
**Got:** Based on the document **"7 Costs That Sink Coffee Shops,"** the seven costs are (pages 1–17):

1. **Over-Scheduling Baristas** (pages 3–4) — Labor is often the highest operational cost. Even one extra barista on a shift a couple times a week can lead to thousands in additional costs per year.

2. **Avoidable Coffee Shop Waste** (pages 5–6) — Wasted food and drinks from hectic rushes, wrong orders, and improper storage add up significantly over time.

3. **Coffee Shop Inventory Management** (pages 6–7) — Trashing perishables, tying up cash in unsold inventory, or running out of stock can sink a...

### q03 — PARTIAL
**Q:** What are five KPIs every coffee shop manager should track?
**Expected source:** `5 KPIs Every Clever Café Manager Should Track` (recall hit: False)
**Retrieved sources:** ['5 KPIs Every Clever Café Manager Should Track', 'Briefing Doc - Opening and Operating a Profitable Coffee Shop', 'Top Metrics to Track to Measure Your Coffee Shop Franchise’s Performance', 'Briefing Doc - Opening and Operating a Profitable Coffee Shop', 'High-Level Strategic Roadmap - Transforming a Declining Coffee Shop…', 'Why Do Coffee Shops Fail', 'Why Do Coffee Shops Fail', '7 Ways To Run A More Efficient Coffee Shop', 'Briefing Doc - Opening and Operating a Profitable Coffee Shop', '7 Costs That Sink Coffee Shops']
**Expected:** Five key performance indicators a café manager should track, including metrics like sales per labor hour, average ticket size, cost of goods sold percentage, customer retention/loyalty rate, and gross profit margin.
**Got:** Based on the document "5 KPIs Every Clever Café Manager Should Track," here are the five KPIs every café manager should track:

1. **Employee Retention Rate** – The percentage of employees who remain with the business over a given period. High turnover is costly due to hiring and training expenses, and incompetent staff can damage the dining experience. (pages 1-2)

2. **RevPASH (Revenue Per Available Seat Hour)** – Measures how efficiently each seat generates revenue by incorporating time and capacity alongside average check size. Calculated as: Total Revenue ÷ Seat Hours. (pages 3-4)

3. **L...

### q05 — PARTIAL
**Q:** How do you calculate the cost of selling 100 coffees?
**Expected source:** `How to Determine the Cost of Selling 100 Coffees` (recall hit: True)
**Retrieved sources:** ['How to Determine the Cost of Selling 100 Coffees', 'Calculating Your Break Even Point', 'How to Determine the Cost of Selling 100 Coffees', 'Briefing Doc - Opening and Operating a Profitable Coffee Shop', 'Briefing Doc - Opening and Operating a Profitable Coffee Shop', 'Calculating Your Break Even Point', '5 KPIs Every Clever Café Manager Should Track', '5 KPIs Every Clever Café Manager Should Track', '7 Costs That Sink Coffee Shops', 'Calculating Your Break Even Point']
**Expected:** A method to compute COGS for 100 coffees by summing per-cup costs of beans, milk, syrups, cups/lids, and labor allocated per cup, then multiplying by 100.
**Got:** ## How to Calculate the Cost of Selling 100 Coffees

Based on the document, here's how to calculate the cost step by step:

### 1. Determine Your Coffee (Espresso) Cost
- Start with your wholesale cost per pound of roasted coffee (example: **$12.00/lb**).
- One pound ≈ 453.59 grams. At **18 grams per double shot**, you get about **25 Americanos per pound**.
- For 100 Americanos: 18g × 100 = **1,800 grams = ~4 lbs** of coffee.
- **Coffee cost: 4 lbs × $12 = $50.00** (i.e., **$0.50 per espresso**).

*(Pages 3–5)*

### 2. Determine Your Cup and Lid Cost
- Example: **$24.00 for 100 cups and lids**...

### q06 — PARTIAL
**Q:** How do you calculate a coffee shop's break-even point?
**Expected source:** `Calculating Your Break Even Point` (recall hit: True)
**Retrieved sources:** ['Briefing Doc - Opening and Operating a Profitable Coffee Shop', 'Calculating Your Break Even Point', 'Calculating Your Break Even Point', 'Briefing Doc - Opening and Operating a Profitable Coffee Shop', 'Briefing Doc - Opening and Operating a Profitable Coffee Shop', 'Calculating Your Break Even Point', 'Why Do Coffee Shops Fail', 'How to Revamp Your Coffee Shop Menu to Make More Profits', 'How to Determine the Cost of Selling 100 Coffees', '5 KPIs Every Clever Café Manager Should Track']
**Expected:** Break-even point = fixed costs divided by (price per unit minus variable cost per unit), giving the number of units that must be sold to cover all costs.
**Got:** ## Calculating a Coffee Shop's Break-Even Point

There are two main approaches described in the documents:

### Simple Formula

**Break-even point = Fixed Costs / Gross Margin %**

- **Fixed costs** are expenses that remain relatively constant (rent, utilities, salaries).
- **Gross margin %** is the percentage of revenue remaining after deducting the cost of goods sold.

**Example:** If fixed costs are $22,000/month and gross margin is 85%:

> $22,000 / 0.85 = **$26,000** in monthly sales needed to break even.

*(Briefing Doc, page 5)*

### Detailed Method (Including Startup Costs)

For a more...

### q12 — PARTIAL
**Q:** How can a coffee shop revamp its menu to increase profits?
**Expected source:** `How to Revamp Your Coffee Shop Menu to Make More Profits` (recall hit: True)
**Retrieved sources:** ['How to Revamp Your Coffee Shop Menu to Make More Profits', 'How to improve sales and profitabiity for your coffe shop', 'How to improve sales and profitabiity for your coffe shop', 'Briefing Doc - Opening and Operating a Profitable Coffee Shop', 'How to Revamp Your Coffee Shop Menu to Make More Profits', 'Briefing Doc - Opening and Operating a Profitable Coffee Shop', 'How to improve sales and profitabiity for your coffe shop', 'How to improve sales and profitabiity for your coffe shop', 'How to Increase Your Coffee Shop Profits with Loyalty Programs', 'How to improve sales and profitabiity for your coffe shop']
**Expected:** Menu engineering tactics: removing low-margin items, highlighting high-margin items with placement and design, introducing premium upsells, simplifying choices, and using psychological pricing.
**Got:** Based on the documents, here are the key strategies for revamping a coffee shop menu to increase profits:

**Start with Data** (pages 2-3, "How to Revamp...")
- Use your POS system to determine what's selling and what's not. This data-driven approach lets you make immediate, informed improvements to your menu.

**Know Your Target Market** (pages 3-4, "How to Revamp...")
- Your target market determines your menu and pricing. College students need quick, moderately-priced items; upscale business areas warrant higher prices with emphasis on quality and uniqueness.
- Visit local competitors to see...

### q14 — PARTIAL
**Q:** What metrics should a coffee shop franchise track to measure performance?
**Expected source:** `Top Metrics to Track to Measure Your Coffee Shop Franchise’s Performance` (recall hit: True)
**Retrieved sources:** ['Top Metrics to Track to Measure Your Coffee Shop Franchise’s Performance', 'Briefing Doc - Opening and Operating a Profitable Coffee Shop', '5 KPIs Every Clever Café Manager Should Track', 'High-Level Strategic Roadmap - Transforming a Declining Coffee Shop…', 'Briefing Doc - Opening and Operating a Profitable Coffee Shop', 'Briefing Doc - Opening and Operating a Profitable Coffee Shop', 'How to Beat Your Coffee Shop Competition', 'How to Increase Your Coffee Shop Profits with Loyalty Programs', 'How to improve sales and profitabiity for your coffe shop', 'Why Do Coffee Shops Fail']
**Expected:** Top franchise performance metrics including same-store sales growth, average ticket, transactions per day, labor cost percentage, COGS percentage, customer retention, and franchisee profitability.
**Got:** Based on the documents, here are the key metrics a coffee shop franchise should track:

**Primary Financial KPIs (PJ's Coffee, pages 1-3):**
- **Cost of Goods (COGs)** – How much it costs to make each menu item; helps adjust inventory and pricing.
- **Labor Percentages** – Labor divided by sales; reveals if you're over- or understaffed during specific day parts.
- **Top-Line Sales** – Gross sales before deducting prime costs; shows selling effectiveness. Should be analyzed alongside bottom-line sales (gross profit) for a full picture of operational efficiency.

**Customer Metrics (PJ's Coffee,...

### q20 — PARTIAL
**Q:** How will finalist team presentations be judged in the capstone?
**Expected source:** `Finalist Team Presentation Judging Rubric S26` (recall hit: True)
**Retrieved sources:** ['Finalist Team Presentation Judging Rubric S26', '🤝 MIS 311 Team Accountability Checklist', 'Student “How to Earn an A” One-Page Guide S26', 'BroadwayCafe Final Project Presentation', 'Broadway_Cafe_Financial_Model_User_Guide', '5 KPIs Every Clever Café Manager Should Track', 'Broadway_Cafe_Financial_Model_Template S26', 'Briefing Doc - Opening and Operating a Profitable Coffee Shop', '7 Ways To Run A More Efficient Coffee Shop', 'Broadway_Cafe_Financial_Model_Template S26']
**Expected:** Judging rubric covering criteria like business case quality, financial model rigor, strategy clarity, presentation delivery, Q&A handling, and team collaboration.
**Got:** Based on the **Finalist Team Presentation Judging Rubric S26** (pages 1–3), finalist presentations are evaluated on a **25-point rubric** across five equally weighted categories (5 points each):

1. **Innovation & Differentiation** — Does the plan create distinctive value beyond just adopting technology? Judges look for originality, competitive advantage, and business relevance.

2. **Business Logic & Feasibility** — Is the execution path realistic, scalable, and credible? Sound assumptions, clear priorities, and strong managerial judgment are expected.

3. **Systems Thinking & Integration** —...
