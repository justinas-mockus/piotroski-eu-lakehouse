# ADR-008: Ticker source: OpenFIGI mapping of GLEIF ISINs

Status: accepted (2026-10-16)

## Context

Gold needs an ISIN and a ticker next to each F-score. The Day 2 Nasdaq Copenhagen screener export (117 rows) has name, currency, price and sector, but no ISIN or ticker, so it cannot join to GLEIF. Joining on company name is ruled out.

GLEIF LEI–ISIN mapping for the 315 ESEF LEIs (2026-10-16 file):

- 4,817 ISINs, but only **132 of 315 LEIs have any ISIN**.
- Mostly debt: 3,594 ISINs are `US`-prefixed, 979 are `DK`. One bank LEI alone has 2,799 ISINs.
- Dual-class issuers (for example A and B shares) have two listed common-stock ISINs under one LEI. "One equity ISIN per company" does not hold.

## Decision

- **Source:** the [OpenFIGI mapping API](https://www.openfigi.com/api/documentation) (`POST /v3/mapping`). `extract/openfigi.py` sends each `DK`-prefixed GLEIF ISIN with `exchCode: "DC"` (Nasdaq Copenhagen). It lands every returned row as `openfigi/ingest_date=YYYY-MM-DD/isin_ticker.csv` (lei, isin, figi, ticker, name, exch_code, security_type, market_sector).
- **No key by default:** 10 jobs per request, 25 requests per minute, about 4 minutes for ~1,000 ISINs. The optional free key comes from the `OPENFIGI_API_KEY` environment variable (100 jobs per request) and is never stored in the repo. The batch size is a parameter, because the docs also mention 5 jobs per request without a key. A 413 response fails with a message to lower it.
- **Grain:** the F-score is per **LEI** (fundamentals are per issuer). Listings are a separate table per **ISIN**. The extractor does not dedup. Silver keeps `security_type = 'Common Stock'`, and gold joins listings one-to-many. It never forces a 1:1 match.
- **The ticker is best-effort.** An LEI without a match keeps its score with a null ticker. Coverage (% of ESEF LEIs with at least one `DC` common-stock listing, plus the list of misses) is a rule in `gold.dq_results` (Day 5).
- The Nasdaq screener export is dropped. Sector would only help to exclude banks and insurers, and the missing-facts rule on Day 4 does that from the data.

## Alternatives considered

- **Nasdaq Nordic list with ISINs.** The screener API blocks automated access, and the official reference file is a paid product.
- **ESMA FIRDS.** Official and free, with ISIN, MIC, CFI code and issuer LEI. It gives Copenhagen equity ISINs directly, without the bond noise. Rejected for the MVP: it has no tickers, and it comes as multi-GB XML, so it is a new extractor and about a day of work. This is the post-MVP fallback if coverage turns out too low.
- **Best-effort with no ticker (ISIN from GLEIF only).** Free, but it leaves the many-to-many problem unsolved, with no way to tell equity from bonds.
- **A per-ticker fundamentals API (FMP, EODHD).** Out of scope (post-MVP v0.3). OpenFIGI is an identifier mapping, not a fundamentals source.

## Consequences

- First run (2026-10-16, no key, about 4 minutes):

  ```text
  status=written isins_sent=979 isins_matched=98 leis_sent=123 leis_matched=92 rows=100
  ```

  The 100 rows are 94 `Common Stock`, 5 `Open-End Fund` and 1 `Preference`. The common stock rows cover **89 LEIs** (28% of 315 ESEF LEIs, 72% of the 123 LEIs with a `DK` ISIN). 94 rows for 89 LEIs confirms the dual-class case (for example `CARLA`, Carlsberg A).
- The coverage ceiling is the GLEIF mapping: at most 132 of 315 ESEF LEIs can get a ticker. Many of the 315 may be bond-only issuers that should have no ticker. Without FIRDS, "missing" cannot be split from "has no listed equity".
- The `DK` prefix filter misses foreign-domiciled companies listed in Copenhagen.
- First North (`DF`) and Dansk OTC (`DD`) are not requested. First North companies do not file ESEF, so nothing is lost.
- **Survivorship bias:** mapping returns listed equities only (`includeUnlistedEquities` is false by default), so delisted companies get no ticker. This is fine for a current snapshot; it matters for any later backtest.
- Tickers are Bloomberg-style. They do not match yfinance symbols (for example `NOVO-B.CO`) without a transformation.
- FIGI data is free to use and redistribute. The API does not return ISINs (third-party licensing), so the extractor keeps the ISIN it sent.
- Idempotency: one file per ingest date. A rerun on the same day is a no-op.
