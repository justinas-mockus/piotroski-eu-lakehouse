# ADR-007: Long-term debt proxy, equity-issuance definition and concept fallbacks

Status: accepted (2026-10-17)

## Context

Two of Piotroski's nine signals use inputs that IFRS filings don't tag directly:

- **ΔLEVER** compares long-term debt (scaled by average total assets) with the prior year. IFRS has no single "long-term debt" concept that Danish filers tag consistently.
- **EQ_OFFER** scores 1 when the company issued no common equity during the year. In the cash-flow statement, `ProceedsFromIssuingShares` is usually left out when nothing was issued, rather than reported as 0.

A coverage check on `silver.fact` (`notebooks/01_silver_explore.py`, 2026-10-17, distinct LEIs out of 315) found:

| Concept | LEIs |
|---|---|
| `ProfitLoss`, `Equity` | 315 |
| `CashFlowsFromUsedInOperatingActivities` | 311 |
| `Liabilities` | 285 |
| `NoncurrentLiabilities` | 265 |
| `Revenue` | 233 |
| `ProceedsFromIssuingShares` | 81 |
| `RevenueFromContractsWithCustomers` | 11 |

`concepts.py` maps each canonical field to an ordered list of `ifrs-full:` concepts (first hit wins), so fallback choices are part of the same decision.

## Decision

1. **Long-term debt = `ifrs-full:NoncurrentLiabilities`.** ΔLEVER uses it as the proxy.
2. **Equity issuance:** a filing issued equity when `ProceedsFromIssuingShares > 0`. When the concept is absent but the filing has a cash-flow statement (`cfo` not null), the company issued no equity and EQ_OFFER is 1. When there's no cash-flow statement either, EQ_OFFER is null. This is an inference from a filed statement that doesn't carry the line, not a default 0 for missing input (ADR-005).
3. **Fallbacks are limited to concepts that measure the same number:**
   - `revenue`: `Revenue`, then `RevenueFromContractsWithCustomers`. `RevenueAndOperatingIncome` is not used, because it includes other operating income.
   - `equity`: `Equity` only. `EquityAttributableToOwnersOfParent` excludes non-controlling interests and would break the Assets = Equity + Liabilities check.
   - `cfo`: `CashFlowsFromUsedInOperatingActivities` only. `CashFlowsFromUsedInOperations` is before interest and tax.
   - `liabilities`: `Liabilities` only, and nullable. It is never derived as `EquityAndLiabilities − Equity`, because the identity check would then pass by construction.
4. **Period type:** balance-sheet fields match only instant facts, and flow fields only duration facts.

## Alternatives considered

- **Borrowings only (non-current borrowings plus lease liabilities)** is closer to Piotroski's "long-term debt". But the concepts filers use for it vary, and summing several of them adds mapping work the Day 4 time-box doesn't allow. Revisit after the MVP.
- **Absent `ProceedsFromIssuingShares` = null.** This is the strictest reading of ADR-005, but EQ_OFFER would be null for about 230 of 311 companies, and nearly every company would lose a signal for a line that is normally left out when it's zero.
- **Wider fallbacks** (owners' equity, operating cash flow before interest and tax, derived liabilities): more coverage, but these are different numbers presented as the same field.

## Consequences

- `NoncurrentLiabilities` includes provisions, deferred tax and other non-debt items, so ΔLEVER measures a broader leverage change than Piotroski's. This is listed as a known limitation in the README.
- EQ_OFFER is available wherever `cfo` is. It scores 1 for a company that issued shares but didn't tag the line. Such filings can't be told apart from real non-issuers.
- `ProceedsFromIssuingShares` also includes issuances other than common stock offerings (e.g. exercised options). Any value above 0 counts as issuance.
- About 80 companies have no mapped revenue, mostly financials that report interest income. Their gross-margin and asset-turnover signals are null.
- Fallback lists change only with a coverage check like the one above, recorded in this ADR.
