# ADR-001: Extraction runs outside Databricks

Status: accepted (2026-10-14)

## Context

The plan assumes the Free Edition workspace may not reach the public data sources (filings.xbrl.org, GLEIF, ECB, Stooq). The day-1 egress spike runs the same request set from a serverless notebook.

Result from the serverless notebook on the verified Free Edition workspace, verbatim:

```text
FAIL ConnectionError https://filings.xbrl.org/api/filings?page[size]=1
FAIL ConnectionError https://leidata-preview.gleif.org/api/v1/lei-records?page[size]=1
FAIL ConnectionError https://data-api.ecb.europa.eu/service/data/EXR/D.USD.EUR.SP00.A?lastNObservations=1
FAIL ConnectionError https://stooq.com/q/l/?s=aapl.us&f=sd2t2ohlcv&h&e=csv
```

All four sources are blocked from the workspace. Per the plan, that moves extraction outside Databricks.

Local check from the development machine (not the spike, recorded for comparison): `filings.xbrl.org/api/filings` answered HTTP 200, `leidata-preview.gleif.org` answered 403, and `stooq.com` answered 404 on the spike URL. These are not the workspace results.

## Decision

Extraction runs outside Databricks. A GitHub Actions job (or the development machine as a fallback) downloads the filings and writes files to a Unity Catalog volume with `databricks fs cp`. Everything from bronze onwards runs inside Databricks.

## Alternatives considered

- **Extract from a serverless notebook with `requests`.** Rejected: the workspace could not reach the sources.
- **Use a cluster with a configured proxy or NAT.** Not available on Free Edition. Serverless only.
- **Pull data by hand and upload it.** Rejected: not repeatable, and the monthly refresh would depend on a person.

## Consequences

- Extraction is a separate pipeline with its own CI schedule (`extract.yml`, planned for Day 6). Idempotency is the extractor's job: it must skip filings already in the manifest.
- The landing volume is the only contact point between the two environments, which matches the firewalled bank-landing pattern.
- Any Databricks-side step that needs internet access has to be redesigned as an extractor step.
- Credentials for the upload live in the GitHub environment secret, not in the repo.
