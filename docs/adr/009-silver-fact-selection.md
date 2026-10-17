# ADR-009: Silver fact selection rules

Status: accepted (2026-10-17)

## Context

Silver turns each raw xBRL-JSON filing (ADR-004) into one row per LEI × fiscal year. Writing the parser from the xBRL-JSON spec alone would have silently lost data. An exploration of all 866 filings in `bronze.esef_filing_raw` (`notebooks/01_silver_explore.py`, 2026-10-17) found:

- **Interim reports are in the data.** Only 525 filings are annual reports. The rest are quarters (68), half years (180), nine-month reports (84), plus 2 filings whose first fiscal year is longer than 400 days. Interim balance sheets would show up as extra "fiscal years", and an interim report's year-end comparatives would override the annual report's figures.
- **Some interim reports carry trailing-twelve-month figures.** One LEI files 7 quarterly and half-year reports with a 365-day duration ending on the report date (e.g. 2024-04-01 to 2025-03-31), so they look annual by length. Their full-year comparative (2024-01-01 to 2024-12-31) ends off the report's yearly cycle, which a real annual report never does. Found on the first `silver.fundamentals` run, where that LEI had 13 "fiscal years".
- **Opening balances are tagged as instants.** The statement of changes in equity reports equity at the start of the comparative year, and some filers tag multi-year history. Taken as fiscal year ends, they produced rows with only `equity` filled in: 1134 rows on the first run, about half of them such fake years.
- **Prefixes vary.** Some filers declare the IFRS namespace as `ifrs_full`, not `ifrs-full`. A prefix is a local alias declared in `documentInfo.namespaces`.
- **Some filers tag every fact with a dimension.** 109 filings carry `ConsolidatedAndSeparateFinancialStatementsAxis` on every fact, all with `SeparateMember`, because they publish single-entity statements only. A "no dimensions at all" rule would have dropped all 109.
- **Facts are duplicated.** The same concept and period appears on several statements, e.g. ProfitLoss on the income, cash-flow and equity statements. On the mapped concepts in annual filings, 45 duplicate groups differ only by rounding (one statement in thousands, another in millions). 8 really conflict: swapped periods, a ×1000 scale error, a reserve included in one copy only.
- **Periods use the next-day midnight convention.** For a 2024-12-31 balance sheet, the instant is `2025-01-01T00:00:00`, and a duration's end works the same way.
- **The same report is sometimes filed twice** (a correction or second version), with the same report end date and different filing ids.
- `entity` is `scheme:<LEI>`. `decimals` is precision, not scale: values are already in full currency units. No filing had more than one entity.

## Decision

1. **Concept:** resolve the prefix through `documentInfo.namespaces`. Any prefix whose URI ends in `/ifrs-full` is rewritten to `ifrs-full:`. Company extension concepts are kept as they are and never mapped.
2. **Non-dimensional:** a fact qualifies when its dimension keys, ignoring `ConsolidatedAndSeparateFinancialStatementsAxis`, are a subset of `concept`, `entity`, `period`, `unit`, `language`.
3. **Scope:** a fact with no consolidation axis or with `ConsolidatedMember` is `consolidated`. A fact with `SeparateMember` is `separate`. Per filing, consolidated facts are used when there are any, otherwise the separate ones. `scope` is kept as a column.
4. **Annual filings only:** a filing is used when it has at least one duration fact of 330–400 days ending on its report end date (from the file name, `{lei}_{period_end}_{filing_id}.json`), and none of its 330–400 day durations ends more than 7 days off the report's yearly cycle (the report end date minus a whole number of years). The 7 days allow for 52/53-week fiscal years. Within an annual filing, a date is a fiscal year end only if a 330–400 day duration ends on it; instants on other dates (opening balances, history) are dropped.
5. **Periods and values:** subtract one day from instants and duration ends; duration starts are used as they are. `lei` is the part of `entity` after `:`. A fact is numeric when `unit` is not null and its value casts to a decimal. `decimals` is never used as a scale.
6. **Duplicates within a filing:** if all values for (concept, period, unit) are within 0.5% of each other, keep the one with the highest `decimals` (the xBRL rule for consistent duplicates). Otherwise the value is null and flagged as a conflict, and gold DQ counts it.
7. **Restatements across filings:** for each LEI and fiscal year end, the filing with the latest report end date wins, tie-broken by `filing_id` as an integer, descending.
8. **Table split:** `silver.fact` is a streaming table and does only row-level work (rules 1, 2, 5 and tagging the scope), so each file is parsed once. Rules 3, 4, 6 and 7 aggregate per filing and run in the `silver.fundamentals` materialized view.

## Alternatives considered

- **Match the literal `ifrs-full:` prefix.** Simpler, but it silently loses every filer with a different alias.
- **Drop every dimensional fact.** It loses the 109 separate-only filers, 13% of the filings.
- **Accept interim reports and keep only annual-length durations.** Flows would be right, but interim instants would still create bogus fiscal years and override comparatives.
- **Treat a filing as interim when any shorter duration ends on its report date.** It catches the trailing-twelve-month reports, but it also drops 6 real annual reports that tag a Q4 quarter.
- **Take the first or the largest value of a conflicting duplicate.** It hides filer errors behind a guess, and missing input must stay null (ADR-005).
- **One streaming table for all of silver.** Per-filing window aggregations aren't supported on streams, and a full materialized view would re-parse every file on every refresh.

## Consequences

- Silver uses 525 of 866 filings. The 339 interim reports (7 of them with trailing-twelve-month figures) and the 2 long first years are excluded on purpose, not lost. The first full run (2026-10-17) gave 815 rows for 302 LEIs, mostly 2–3 fiscal years each, with `assets`, `profit_loss` and `cfo` null in under 2% of rows.
- A restatement replaces the whole row (rule 7). If the newer filing's comparatives leave out a field the older filing had, that field is null for the year. Filling field by field across filings would recover it, but mixes figures from different filings. Known limitation.
- Companies scored on separate statements are visible through `scope`. For a company without subsidiaries, separate and consolidated mean the same thing.
- Conflicting duplicates become null inputs, so the affected signals are null, not guessed. Gold DQ reports the count.
- The 2 long first fiscal years produce no annual flows for that year. This is listed as a known limitation.
- The rules depend on the file name the extractor writes (`extract/esef_filings.py`). Changing it breaks rules 4 and 7.
