# Piotroski EU Lakehouse — Project Plan

Oct 13, 2026 · @Justinas

## Scope and MVP definition of done

The MVP is due by 2026-10-20. It produces a gold table with a Piotroski F-score (0–9) for every company in one EU country, built from free ESEF filings. It is deployed to Databricks by GitHub Actions and documented well enough to walk through in a 20-minute interview.

**Definition of done (all must be true by day 7):**

- [ ] One command (`databricks bundle deploy -t prod` run by CI on merge to `main`) deploys everything. Nothing is created by hand in the UI except the workspace itself.
- [ ] Extraction lands raw xBRL-JSON files plus a manifest in a Unity Catalog volume. It is idempotent: re-running it downloads nothing new.
- [ ] Bronze, silver and gold tables exist, using Auto Loader and a declarative pipeline, with data quality expectations on silver.
- [ ] `gold.piotroski_score` has all 9 signals as separate columns, plus `data_completeness`, so the reader can see which signals were missing rather than silently scored 0.
- [ ] Accounting identity reconciliation (Assets = Equity + Liabilities, within tolerance) runs on silver. Failures are counted in a DQ table, not hidden.
- [ ] Unit tests for the pure-Python logic (concept mapping, signal maths) run in CI on every PR.
- [ ] README with an architecture diagram, a "how to run" section, a top-10 output sample, known limitations, and links to at least 5 ADRs.
- [ ] A dashboard (Databricks AI/BI) showing the score distribution and DQ failure counts.

**Out of scope for the MVP:** Magic Formula, Altman Z, Beneish M, prices, multi-country, dbt, Terraform, AWS, the rate-limited ticker API. Each one is a post-MVP milestone (last section). Bring anything new in only when the definition of done above is green.

**Realism check:** at 3–5 h/day, a week is about 25–30 hours. That's enough only if silver mapping is time-boxed. Mapping IFRS tags to Piotroski inputs is where the week will slip (day 4). The rule: map the top concepts, mark the rest as missing, and move on.

## Constraints and data sources

Free Edition gives serverless compute only, restricted outbound internet (loosened, not removed, by LinkedIn verification), a cap of 5 concurrent job tasks, and non-commercial use ([Databricks docs](https://docs.databricks.com/aws/en/getting-started/free-edition-limitations)). Data volume is not a constraint: one country's ESEF filings is a few hundred MB of JSON.

### Day-1 spike: does your verified workspace reach the sources?

Run this in a serverless notebook. Each URL either returns an HTTP status or fails with a connection or DNS error. A failure means blocked, and that source's extraction moves to GitHub Actions.

```python
import requests

for url in [
    "https://filings.xbrl.org/api/filings?page[size]=1",
    "https://leidata-preview.gleif.org/api/v1/lei-records?page[size]=1",
    "https://data-api.ecb.europa.eu/service/data/EXR/D.USD.EUR.SP00.A?lastNObservations=1",
    "https://stooq.com/q/l/?s=aapl.us&f=sd2t2ohlcv&h&e=csv",
]:
    try:
        r = requests.get(url, timeout=15)
        print("OK  ", r.status_code, url)
    except Exception as e:
        print("FAIL", type(e).__name__, url)
```

Record the output verbatim in ADR-001. The design works either way. Default: **extract outside Databricks** (a GitHub Actions job, or your PC as a fallback) and upload to a UC volume with `databricks fs cp`. That's the pattern a real firewalled bank lakehouse uses, so it's a better interview story than "the notebook called requests".

### Sources

| Source | What it gives | Role | Gotchas |
| --- | --- | --- | --- |
| [filings.xbrl.org API](https://filings.xbrl.org/docs/about) | ESEF annual reports as xBRL-JSON, indexed by LEI, period and country | Primary fundamentals (MVP) | Not complete coverage. IFRS tags plus company extensions. Each filing has current and prior year, so one filing yields both Piotroski periods. |
| GLEIF LEI–ISIN mapping file | LEI → ISIN | Join key to tickers (MVP) | Many-to-many (one LEI, many ISINs). Needs a dedup rule. |
| Exchange equity list for the chosen country (e.g. the Euronext or Nasdaq Nordic listings download) | ISIN, ticker, market, sector | Universe and ticker (MVP) | Manual CSV download. Store the snapshot date. |
| ECB FX reference rates | Daily EUR crosses | Currency normalisation (MVP if the country isn't euro) | Only matters for non-EUR filers. |
| Stooq | Daily prices | Post-MVP (market cap, Magic Formula) | Unofficial, can change without notice. |
| Rate-limited fundamentals API (FMP / EODHD / Alpha Vantage free tier) | Per-ticker statements | Post-MVP source #3, a cross-check | Free tiers have small daily quotas. Check current terms and don't publish their data in the repo. |
| yfinance | Per-ticker statements | Local cross-check only | Yahoo terms forbid redistribution. Never commit its output. |

### Choosing the country (day 1, by data, not guesswork)

Query the filings.xbrl.org API, count filings per country for the last 2 fiscal years, and pick the country with the most filings that have 0 validation errors. Your preference for the biggest market is right, but coverage on this site varies by country: some national filing registries are hard to scrape, so a big economy can be thin. The count query is itself a commit (`notebooks/00_country_profiling`), and the result goes into ADR-002.

## Architecture

Extraction runs outside Databricks and only lands files. That keeps it working even if the day-1 egress test shows the sources are blocked from the workspace. Everything from bronze onwards is declarative and deployed by CI.

&#91;embedded content: target architecture · extract outside, medallion inside, CI deploys\]

The arrow from Deploy into the workspace is the only way code reaches prod; nothing is clicked together in the UI.

## Local setup, repo layout and AI agents

### Tools (Linux or Windows, \~1.5 h)

| Tool | Why | Check |
| --- | --- | --- |
| Python matching your serverless environment | Local tests behave like the cluster | `import sys; print(sys.version)` in a workspace notebook, then pin it with uv |
| [uv](https://docs.astral.sh/uv/) | Env, lockfile, fast CI installs | `uv --version` |
| Databricks CLI (recent; bundles are now called Declarative Automation Bundles) | Bundle validate, deploy, run; `fs cp` to volumes | `databricks -v`, then `databricks auth login --host <workspace-url>` |
| Java 17 | Local PySpark for unit tests | `java -version` |
| pre-commit + ruff + gitleaks | Lint, format, block secrets before they reach Git | `pre-commit run --all-files` |
| GitHub CLI | PRs from the terminal | `gh auth status` |

**VS Code extensions:** Databricks (official: bundle explorer, Databricks Connect run/debug), Python + Pylance, Ruff, YAML (Red Hat; validates `databricks.yml` against the bundle JSON schema), GitLens (optional), Claude Code. Nothing else.

### Repo layout

```text
piotroski-eu-lakehouse/
├── databricks.yml              # bundle root: targets dev / prod, variables
├── resources/                  # jobs, pipelines, volumes as YAML
│   ├── pipeline_fundamentals.yml
│   └── job_daily.yml
├── extract/                    # runs OUTSIDE Databricks (GH Actions / PC)
│   ├── esef_filings.py         # list + download xBRL-JSON, write manifest
│   ├── gleif_isin.py
│   └── upload_to_volume.sh
├── src/piotroski/              # pure Python, imported by pipeline + tests
│   ├── concepts.py             # IFRS tag -> canonical field mapping
│   ├── signals.py              # the 9 signals as functions on DataFrames
│   └── dq.py                   # reconciliation rules
├── pipelines/                  # declarative pipeline definitions (bronze/silver/gold)
├── notebooks/                  # exploration only; never imported
├── tests/unit/  tests/fixtures/  # small hand-made JSON, NOT real downloads
├── docs/adr/  docs/architecture.md  docs/PLAN.md
├── .github/workflows/  ci.yml  deploy.yml  extract.yml
├── .claude/agents/  planner.md  reviewer.md
├── CLAUDE.md  README.md  pyproject.toml  uv.lock  .pre-commit-config.yaml  .gitignore
```

The rule that makes this testable: business logic lives in `src/piotroski/` as functions of `DataFrame -> DataFrame`. Pipeline files only wire them together. Notebooks are scratch space.

### The two agents

- **`planner.md`** reads `docs/PLAN.md` and the ADRs. It breaks the next task into steps and acceptance criteria, and it does **not** write code. It pushes back on scope creep against the definition of done.
- **`reviewer.md`** reviews a diff (`git diff main...HEAD`) against a fixed checklist: idempotency, secrets, tests present, naming, ADR needed?, can-you-explain-it. It answers with blocking and non-blocking comments.
- **`CLAUDE.md`** holds house rules: never commit data or secrets, conventional commits, Python version, "ask before writing more than \~30 lines", explain any API it suggests. That last rule keeps the code yours.

**Write by hand:** `signals.py`, `concepts.py`, `dq.py`, the pipeline definitions, `databricks.yml`. **Fine to pair on with AI:** GitHub Actions YAML, README prose, diagram code, the extractor's retry and pagination boilerplate.

## Week 1: day-by-day MVP plan (Oct 14–20)

Each day ends with a merged PR to `main`. If a day overruns by more than 2 hours, cut scope from that day. Don't push the remaining days back.

### Day 1 (Wed Oct 14): foundations and facts

- [x] Create the GitHub repo (public, MIT licence, `.gitignore` for Python plus `data/`, `*.json` outside `tests/fixtures`). Protect `main`: PR required, CI must pass.
- [x] Install the local tools; run `databricks auth login`; run the egress spike notebook → **ADR-001** (where extraction runs).
- [x] Run country profiling against the filings API → **ADR-002** (which country and why, with the counts).
- [x] `uv init`, pre-commit with ruff + gitleaks, an empty `src/piotroski/`, one passing dummy test.
- [x] Write `CLAUDE.md` and the two agent files; copy this plan to `docs/PLAN.md`.

### Day 2 (Thu Oct 15): extraction to landing

- [x] `extract/esef_filings.py`: page through the API filtered by country, download each filing's xBRL-JSON, write `manifest.jsonl` (LEI, period end, filing id, URL, sha256, downloaded\_at).
- [x] Idempotency: skip filings already in the manifest. Retry with backoff. Polite rate limit (1 request/s).
- [x] `extract/gleif_isin.py` and the exchange list CSV (a manual download is fine; record the date). The exchange list has no ISIN or ticker, so choosing that source moves to Day 3.
- [x] Create a UC volume `landing` per target; upload with `databricks fs cp -r`. Layout: `/Volumes/<catalog>/<schema>/landing/esef/ingest_date=YYYY-MM-DD/`. Done for `dev`; `prod` is created before the first prod deploy (ADR-003).

### Day 3 (Fri Oct 16): bronze with Auto Loader

- [ ] Bronze table `bronze.esef_filing_raw`: Auto Loader, each file read **whole as text** plus `_metadata.file_path` and ingest timestamp. Don't infer a schema from xBRL-JSON: facts are a map keyed by fact id, and inference explodes into thousands of columns → **ADR-004**.
- [ ] Pick an ISIN/ticker source for the exchange list and record it in a new ADR. The Day 2 Nasdaq Copenhagen screener export (117 rows) has no ISIN or ticker, so it cannot join to GLEIF. Avoid joining on company name. If no source turns up within the time-box, make the ticker best-effort and say so in the ADR.
- [ ] `bronze.lei_isin` and `bronze.exchange_listing` as plain CSV loads. The Nasdaq export has a UTF-8 BOM and price columns (out of scope; keep only what is needed).
- [ ] First `databricks.yml` with a `dev` target; deploy from VS Code; pipeline runs green. The catalog comes from SQL `CREATE CATALOG`; check whether the bundle `catalogs` resource works on Free Edition (ADR-003). Auto Loader on `esef/` needs `pathGlobFilter="*.json"` to skip `manifest.jsonl`.

### Day 4 (Sat Oct 17): silver, the hard day (time-box: 6 h)

- [ ] `silver.fact`: parse with `from_json` to `MAP<STRING, STRUCT<value, decimals, dimensions MAP>>`, explode, and keep **non-dimensional** facts only (no segment or axis members). That gives consolidated totals.
- [ ] Parse periods: instant vs. duration. Map each to fiscal year end.
- [ ] `concepts.py`: a mapping table from canonical field to an ordered list of `ifrs-full:` concepts (first hit wins). Start with: `ProfitLoss`, `Assets`, `CashFlowsFromUsedInOperatingActivities`, `CurrentAssets`, `CurrentLiabilities`, `NoncurrentLiabilities` (proxy for long-term debt; record it in ADR), `Revenue`, `GrossProfit` / `CostOfSales`, `ProceedsFromIssuingShares`.
- [ ] `silver.fundamentals`: one row per LEI × fiscal year, a column per canonical field, currency column, source filing id. Dedupe restatements: the newest filing wins for a given year.
- [ ] Expectations: `Assets > 0`, the currency is ISO, fiscal year within range → drop or quarantine (decide and write it down).

### Day 5 (Sun Oct 18): gold and tests

- [ ] `signals.py`: the 9 signals, each returning 1 / 0 / null. Null means missing input, never 0 → **ADR-005**.
- [ ] `gold.piotroski_score`: signals, `f_score = sum of non-null`, `signals_available`, joined to ISIN and ticker.
- [ ] Unit tests with hand-made fixtures: one company per edge case (all 9 met, missing gross profit, negative equity, restated year).
- [ ] `dq.py` + `gold.dq_results`: balance-sheet identity check, % of companies with all 9 signals, unmapped LEIs.

### Day 6 (Mon Oct 19): CI/CD and orchestration

- [ ] `ci.yml` on PR: ruff, pytest, `databricks bundle validate -t dev`.
- [ ] `deploy.yml` on merge to `main`: `bundle deploy -t prod`, then `bundle run` of the job. Auth via a GitHub environment secret → **ADR-006** (service principal OAuth if Free Edition allows it, otherwise a short-lived PAT; write down which and why).
- [ ] `extract.yml`: manual `workflow_dispatch` plus a monthly cron that runs the extractor and uploads to the prod volume.
- [ ] A job in `resources/job_daily.yml`: pipeline refresh → DQ task → failure email notification.

### Day 7 (Tue Oct 20): make it presentable

- [ ] README: problem, the diagram, a results sample, how to run, limitations, an ADR index.
- [ ] AI/BI dashboard: score distribution, top 20, DQ failures over runs.
- [ ] Ask the reviewer agent for a full-repo review; fix the blocking comments.

## Testing, data quality, CI/CD and monitoring

The testing strategy has three layers, and each catches a different class of bug. Lean on the reconciliation layer hardest: it's your DataCompy experience applied to a new domain.

| Layer | What | Where it runs | Catches |
| --- | --- | --- | --- |
| Unit | pytest on `src/piotroski/` with local PySpark and hand-made fixtures | GitHub Actions, every PR | Wrong signal maths, broken concept mapping |
| Pipeline expectations | Declarative pipeline expectations on silver (warn / drop / fail per rule) | Databricks, every run | Bad rows from messy filings |
| Reconciliation | Assets = Equity + Liabilities (±1%); current assets ≤ total assets; spot check of 3 companies against their PDF reports | Databricks DQ task + a manual notebook | Wrong concept picked, unit or scale errors, dimensional facts leaking in |

### Environments on one Free Edition workspace

There are two bundle targets. `dev` deploys in development mode, so resource names get your username as a prefix and schedules are paused. `prod` is deployed only by CI. Data is separated by catalog per target if Free Edition lets you create catalogs, otherwise by schema prefix (`dev_bronze`, `prod_bronze`). That decision goes in **ADR-003**.

### CI/CD flow

1. Feature branch → PR → `ci.yml`: ruff, pytest, `bundle validate`.
2. Optional: comment `/deploy-dev` or run a manual workflow to deploy the PR to `dev`.
3. Merge → `deploy.yml`: `bundle deploy -t prod` → `bundle run` of the job → workflow fails if the job fails.
4. `extract.yml` runs separately on a monthly cron. Fundamentals change once or twice a year, and monthly picks up late filers.

### Monitoring (scaled to a portfolio project)

- Job failure → email notification (in the job YAML).
- `gold.dq_results`: one row per run per rule, with counts. The dashboard shows the trend.
- The pipeline event log for expectation pass/fail rates.
- `extract/` writes a run summary (new / skipped / failed filings) into the manifest and the GitHub Actions job summary.
- Use system tables only if Free Edition exposes them; check before planning around them.

## ADRs, commit hygiene and security

Write ADRs as short Markdown files in `docs/adr/NNN-title.md` with four headings: Context, Decision, Alternatives considered, Consequences. Keep each one to a page or less. Write it the day the decision is made, while the reason is still fresh.

| ADR | Decision | Day |
| --- | --- | --- |
| 001 | Extraction runs outside Databricks (egress test result) | 1 |
| 002 | Country choice, with filing counts | 1 |
| 003 | Environment isolation on one workspace: catalogs or schema prefixes | 3 |
| 004 | Bronze stores raw xBRL-JSON as text; parsing happens in silver | 3 |
| 005 | Missing input = null signal, never 0; `signals_available` exposed | 5 |
| 006 | CI auth method for Free Edition | 6 |
| 007 | Long-term debt proxy and equity-issuance definition | 4 |
| 008+ | One per Free Edition limit you actually hit, with the error message | as hit |

### Commit and PR hygiene

- Conventional commits (`feat(silver): map current assets concepts`). One logical change per commit; one day's theme per PR.
- The PR template has three questions: what changed, how you tested it, and whether an ADR is needed.
- Squash-merge to `main` so history reads as one line per feature. Tag `v0.1.0` at the MVP.

### Security and data rules (non-negotiable)

- No tokens anywhere in the repo. Locally use `~/.databrickscfg` from `auth login` (outside the repo). In CI use a GitHub environment secret. gitleaks runs in pre-commit **and** in CI.
- No downloaded data in Git: real filings, yfinance output and API responses stay in the volume or in a gitignored `data/`. Test fixtures are hand-written and tiny.
- The workspace URL is fine to publish. Workspace IDs, user emails and tokens are not; scrub screenshots before they go in the README.

## After the MVP

Each milestone is about 2–4 days and starts only after the previous one is merged and tagged.

1. **v0.2: prices and market cap.** Stooq daily prices, ECB FX, `gold.market_cap`. Piotroski's original screen ranks only the highest book-to-market quintile, so this makes the score faithful. It's also the first incremental, daily-changing source, which is a chance to use MERGE / SCD on top of the one-off fundamentals.
2. **v0.3: rate-limited ticker API (your idea).** A queue table of tickers, a daily job pulling N tickers within the free quota, watermark and retry state stored in Delta. It shows backfill under quotas, a very common real-world pattern. Use it as a cross-check source against ESEF (source-vs-source reconciliation report).
3. **v0.4: more scores.** Altman Z, Magic Formula, Beneish M on the same silver. If the silver model was right, each one is about a day. If it's painful, that's a talking point about the model too.
4. **v0.5: second country.** Tests whether `concepts.py` generalises. Expect new extension tags.
5. **v0.6: dbt on gold** (dbt-databricks) as a comparison with declarative pipelines, plus **Terraform** for workspace objects, catalogs and grants. This closes the secondary-goal gaps.
6. **Optional: AWS.** S3 landing + Lambda extractor via Terraform, only if a Free Edition limit forces it.
