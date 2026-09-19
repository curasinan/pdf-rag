# Second generation seed — is the arm ordering stable?

- Reseeded: **h01, h02, h03, h04, h05, h06** (4 discordant in seed 1, 2 same-type control)
- Discordant across the full study: **h01, h02, h05, h06** — these carry 100% of the paired quality signal; the other 21 questions scored identically across all three arms.
- Seed 2 is an independent draw: the CLI exposes no temperature or seed, so a rerun cannot be made reproducible.

## Per-question, per-arm: seed 1 → seed 2

| qid | stratum | arm | verdict | relevance |
|---|---|---|---|---|
| h01 | discordant | A | PARTIAL → DIFFERENT ⚠ | 3 → 1  (-2) |
| h01 | discordant | B | EQUIVALENT → EQUIVALENT | 5 → 5 |
| h01 | discordant | C | EQUIVALENT → EQUIVALENT | 5 → 5 |
| h02 | discordant | A | EQUIVALENT → EQUIVALENT | 4 → 4 |
| h02 | discordant | B | EQUIVALENT → EQUIVALENT | 4 → 4 |
| h02 | discordant | C | EQUIVALENT → EQUIVALENT | 5 → 5 |
| h03 | control | A | EQUIVALENT → EQUIVALENT | 5 → 5 |
| h03 | control | B | EQUIVALENT → EQUIVALENT | 5 → 5 |
| h03 | control | C | EQUIVALENT → EQUIVALENT | 5 → 5 |
| h04 | control | A | EQUIVALENT → EQUIVALENT | 4 → 4 |
| h04 | control | B | EQUIVALENT → EQUIVALENT | 4 → 4 |
| h04 | control | C | EQUIVALENT → EQUIVALENT | 4 → 4 |
| h05 | discordant | A | EQUIVALENT → EQUIVALENT | 4 → 5  (+1) |
| h05 | discordant | B | EQUIVALENT → EQUIVALENT | 5 → 4  (-1) |
| h05 | discordant | C | EQUIVALENT → EQUIVALENT | 5 → 5 |
| h06 | discordant | A | DIFFERENT → PARTIAL ⚠ | 2 → 3  (+1) |
| h06 | discordant | B | DIFFERENT → EQUIVALENT ⚠ | 2 → 4  (+2) |
| h06 | discordant | C | EQUIVALENT → EQUIVALENT | 5 → 5 |

## Drift by stratum

| stratum | cells | verdict flip | relevance flip | mean abs Δrel |
|---|---|---|---|---|
| all | 18 | 0.17 | 0.28 | 0.39 |
| discordant | 12 | 0.25 | 0.42 | 0.58 |
| control | 6 | 0.00 | 0.00 | 0.00 |

The **control** row is the load-bearing one. Discordant questions were selected for being extreme in seed 1, so some regression to the mean is guaranteed regardless of whether the arm difference is real. Control drift is the baseline that makes discordant drift interpretable.

## Drift by arm

| arm | verdict flip | 95% CI | relevance flip | judge-only flip (seed 1) |
|---|---|---|---|---|
| A — hybrid RAG | 2/6 = 0.33 | [0.04, 0.78] | 0.50 | 0.33 |
| B — whole corpus | 1/6 = 0.17 | [0.00, 0.64] | 0.33 | 0.25 |
| C — agentic files | 0/6 = 0.00 | [0.00, 0.46] | 0.00 | 0.08 |

Seed-to-seed flip bundles generation *and* judge noise — each seed is judged afresh. The judge-only column is its contribution measured on identical answers, so the excess over it is what regeneration adds.

**Read the CI, not the point estimate.** Six cells per arm is few: a clean 0/6 is still consistent with a true flip rate near 40%, so "0.00" here means "no drift observed", never "proven stable".

## Where arm A's drift comes from

Arm A retrieved the **identical** chunk set in both seeds on **6/6** reseeded questions — every one. MRR@10 is unchanged throughout (h01 0.00, h02 1.00, h03 0.50, h04 0.33, h05 1.00, h06 1.00).

So none of arm A's instability is retrieval instability. Given the same chunks it writes a differently-worded answer, and the score follows the wording. The corollary matters more: a retrieval **failure** like h01's (MRR 0.0 in both seeds) is fully reproducible, not a bad draw.

## Study-wide result under each view

### Seed 1 (as published)

| arm | EQUIVALENT | rel mean |
|---|---|---|
| A | 23/25 | 4.68 |
| B | 24/25 | 4.80 |
| C | 25/25 | 4.96 |

| pair | b | c | McNemar p | Holm p | Δ relevance [95% CI] |
|---|---|---|---|---|---|
| A vs B | 0 | 1 | 1.000 | 1.000 | -0.12 [-0.32, 0.00] |
| A vs C | 0 | 2 | 0.500 | 1.000 | -0.28 [-0.60, -0.04] |
| B vs C | 0 | 1 | 1.000 | 1.000 | -0.16 [-0.44, 0.00] |

### Seed 2 substituted

| arm | EQUIVALENT | rel mean |
|---|---|---|
| A | 23/25 | 4.68 |
| B | 25/25 | 4.84 |
| C | 25/25 | 4.96 |

| pair | b | c | McNemar p | Holm p | Δ relevance [95% CI] |
|---|---|---|---|---|---|
| A vs B | 0 | 2 | 0.500 | 1.000 | -0.16 [-0.52, 0.08] |
| A vs C | 0 | 2 | 0.500 | 1.000 | -0.28 [-0.68, 0.00] |
| B vs C | 0 | 0 | 1.000 | 1.000 | -0.12 [-0.24, 0.00] |

### Pooled (mean of both draws)

| arm | EQUIVALENT | rel mean |
|---|---|---|
| A | 23/25 | 4.68 |
| B | 24/25 | 4.82 |
| C | 25/25 | 4.96 |

| pair | b | c | McNemar p | Holm p | Δ relevance [95% CI] |
|---|---|---|---|---|---|
| A vs B | 0 | 1 | 1.000 | 1.000 | -0.14 [-0.40, 0.00] |
| A vs C | 0 | 2 | 0.500 | 1.000 | -0.28 [-0.60, -0.02] |
| B vs C | 0 | 1 | 1.000 | 1.000 | -0.14 [-0.32, 0.00] |

In the pooled view a question counts as a pass only if it passed in **both** draws — a one-of-two pass is exactly the instability under test, and averaging it away would hide the finding.