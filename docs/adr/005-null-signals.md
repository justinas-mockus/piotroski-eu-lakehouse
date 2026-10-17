# ADR-005: Missing input is a null signal; signal definitions

Status: accepted (2026-10-17)

## Context

Piotroski's F-score adds nine binary signals. Screeners usually score a signal 0 when its input is missing, so a company with a thin filing looks financially weak instead of unknown. In `silver.fundamentals` (ADR-009), inputs are missing for structural reasons: about 80 companies have no mapped revenue (ADR-007), conflicting duplicates are nulled (ADR-009 rule 6), and each LEI has only 2–3 fiscal years, so its first year has no prior year to compare with.

Piotroski scales by beginning-of-year total assets (ROA, cash flow, asset turnover) and average total assets (leverage). A change in ROA then needs total assets from two years back, so with 2–3 years per LEI most companies would get at most one year with ΔROA.

A check on `silver.fundamentals` (`notebooks/02_gold_explore.py`, 2026-10-17) found `cost_of_sales` positive in 330 rows and negative in 2, and 33 LEI-years without `GrossProfit` that have both `Revenue` and `CostOfSales`.

## Decision

1. **Missing input gives a null signal, never 0.** Each signal is 1, 0 or null. A comparison with a null input is null.
2. **Score columns:** `f_score` is the sum of the non-null signals, `signals_available` is how many are non-null (0–9), and `data_completeness = signals_available / 9`. A score is read together with `signals_available`.
3. **Prior year:** the previous `silver.fundamentals` row for the same LEI, used only when its `fiscal_year_end` is 330–400 days earlier (the annual range from ADR-009 rule 4). If there's a gap or no earlier row, every change signal is null.
4. **Denominator:** ratios use end-of-year total assets of the same year, so every change signal needs only years t and t−1.
5. **Signals** (t = this year, t−1 = prior year):

   | Signal | 1 when |
   |---|---|
   | `f_roa` | profit_loss / assets > 0 |
   | `f_cfo` | cfo > 0 |
   | `f_delta_roa` | ROA(t) > ROA(t−1) |
   | `f_accrual` | cfo > profit_loss |
   | `f_delta_lever` | noncurrent_liabilities / assets(t) < the same ratio at t−1 (proxy, ADR-007) |
   | `f_delta_liquid` | current_assets / current_liabilities(t) > the same ratio at t−1 |
   | `f_eq_offer` | no equity issued, as defined in ADR-007 rule 2 |
   | `f_delta_margin` | gross_profit / revenue(t) > the same ratio at t−1 |
   | `f_delta_turn` | revenue / assets(t) > the same ratio at t−1 |

6. **Ties score 0:** a change signal needs a strict improvement.
7. **Gross profit** = `GrossProfit` when it's tagged, otherwise `revenue − abs(cost_of_sales)`. `abs` handles the 2 filers who tag cost of sales as a negative number.

## Alternatives considered

- **Missing = 0** (classic screeners). The score stays comparable on one 0–9 scale, but missing data turns into a "weak" verdict. This breaks the project rule that missing input means a null signal.
- **Piotroski's denominators** (beginning-of-year assets for ROA, cash flow and turnover; average assets for leverage). This is the faithful version, but ΔROA, ΔLEVER and ΔTURN would need three years per LEI, and most companies have two or three.
- **Score only complete rows** (`signals_available = 9`). The score is clean, but it hides most companies, including all the financials without revenue.
- **Rescale to 9** (`f_score × 9 / signals_available`). It looks comparable, but it invents precision. A ranking can filter on `signals_available` instead.

## Consequences

- `f_score` values from rows with different `signals_available` are not on the same scale. A 4 out of 4 is not a 4 out of 9. The README and the dashboard show both columns, and a ranking filters on `signals_available` first.
- The first year of each LEI has at most 4 signals (`f_roa`, `f_cfo`, `f_accrual`, `f_eq_offer`).
- End-of-year assets make ROA and turnover include this year's asset growth. A company that grows its assets fast looks slightly worse than under Piotroski's definition. This is listed as a known limitation.
- Since `silver.fundamentals` drops rows with `assets <= 0`, `f_roa` has the same sign as `profit_loss`. It's still null when assets are missing.
- Restated figures come into the change signals automatically: the prior-year row is the newest filing's comparative (ADR-009 rule 7).
