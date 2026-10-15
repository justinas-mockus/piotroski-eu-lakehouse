# ADR-002: Country choice: Denmark (DK)

Status: accepted (2026-10-14)

## Context

The MVP scores every company in one EU country from ESEF filings. The plan picks the country by data: count filings per country on filings.xbrl.org for the last two fiscal years, and choose the country with the most filings that have 0 validation errors.

Count run on 2026-10-14 against the full filings list (26,009 filings, page size 1000). Period ends in 2024 and 2025 were kept. "Clean" means `error_count == 0`. "Entities" is the registry id taken from `json_url`, not the LEI.

| Country | Filings | Clean | Entities | Clean entities |
| --- | ---: | ---: | ---: | ---: |
| GB (not EU) | 1140 | 1130 | 630 | 628 |
| UA (not EU) | 1218 | 1064 | 1150 | 999 |
| **DK** | 939 | **866** | 327 | 315 |
| FR | 409 | 344 | 227 | 215 |
| FI | 380 | 369 | 139 | 137 |
| SE | 355 | 351 | 345 | 341 |
| IT | 324 | 322 | 171 | 171 |
| NL | 243 | 240 | 130 | 128 |
| NO (not EU) | 224 | 221 | 220 | 217 |
| BE | 193 | 191 | 80 | 80 |
| AT | 193 | 187 | 79 | 79 |
| ES | 114 | 114 | 113 | 113 |

Germany (DE) has no filings in the index for these period ends. The filings API returned 0 for DE in a country filter probe.

EU countries with fewer than 114 filings (the Spain count) are omitted.

## Decision

Use **Denmark (DK)**. It has the most EU filings with 0 validation errors for the last two period ends (866), and 315 clean entities.

GB and UA are excluded: they have more clean filings, but they are not EU countries. NO is excluded for the same reason.

## Alternatives considered

- **Finland (FI)**: 369 clean filings, 137 clean entities. Second-best EU option by clean count, and a smaller universe.
- **Sweden (SE)**: 351 clean filings, 341 entities, which is close to one filing per entity. Good coverage, but a smaller clean count.
- **France (FR)**: 344 clean filings, but 215 entities. Larger market, but about 1.6 filings per entity.
- **Germany (DE)**: the largest EU economy, but no filings in the index, so not possible.
- **GB or UA**: not EU. Ruled out by the MVP scope.

## Consequences

- The universe is Danish filers in the filings index. The count is from the index only; it does not confirm that every Danish listed company has an ESEF filing.
- Piotroski needs the current and prior fiscal year for each company. A filing covers both, but the count above does not check that every entity has both 2024 and 2025 filings clean. That check is the next step in the silver work (Day 4) and may cut the universe below 315.
- The count is a point-in-time snapshot. The raw count script is kept with the scratch notes, not in the repo yet. It moves to `notebooks/00_country_profiling` in the Day 1 commit.
- Danish filers report in DKK. Currency normalisation (ECB FX) is needed only if the chosen filings are non-EUR. The FX source is noted for Day 4 and ADR-007.
