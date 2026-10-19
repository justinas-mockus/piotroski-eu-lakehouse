# ADR-011: The AI/BI dashboard is a bundle resource, authored in the UI

Status: accepted (2026-10-19)

## Context

The definition of done requires an AI/BI dashboard (score distribution, top 20, DQ failures over runs) and also says nothing is created by hand in the UI except the workspace. A dashboard is a JSON document (`.lvdash.json`) that is easiest to build in the AI/BI editor and awkward to write by hand. It also has to work in both targets: dev reads `piotroski_dev.gold`, prod reads `piotroski_prod.gold`, and prod is owned by the CI service principal (ADR-003, ADR-006).

## Decision

1. Author the dashboard once in the UI against `piotroski_dev`. Dataset SQL uses unqualified table names (`piotroski_score`, `dq_results_history`).
2. Pull it into the repo with `databricks bundle generate dashboard --existing-id <id>`, keep it as `dashboards/piotroski.lvdash.json`, and declare it in `resources/dashboard_piotroski.yml`. Bind the UI copy in dev (`bundle deployment bind`), so there is one dashboard per target.
3. The resource sets `dataset_catalog: ${var.catalog}` and `dataset_schema: gold`, which override every dataset's catalog and schema at deploy time. The `"catalog": "piotroski_dev"` left in the generated JSON is expected: `bundle validate -t prod -o json` shows `dataset_catalog: piotroski_prod`.
4. `warehouse_id` comes from a lookup variable (`lookup: warehouse: Serverless Starter Warehouse`), so no warehouse ID is committed and each deployer resolves its own.
5. `embed_credentials: true`: the published dashboard queries as its publisher. In prod that is the service principal, so viewers need no grants on `piotroski_prod.gold`. The data is public filings.

## Alternatives considered

- **UI-only dashboard.** Quickest, but it breaks the DoD and would not exist in prod after a deploy.
- **Hand-written `.lvdash.json`.** Fully "by hand", but the widget spec is verbose and undocumented in places; generating it from the editor is the documented path.
- **Catalog-qualified SQL per target.** Needs two JSON files or templating. `dataset_catalog` does it in one line.
- **`embed_credentials: false` plus `GRANT SELECT` on prod gold to `account users`.** Each viewer then queries as themselves. Same visible result with one more grant to manage; not needed for a public-data portfolio dashboard.

## Consequences

- Edits made in the UI drift from the repo and are overwritten on the next deploy. To keep one, re-run `bundle generate dashboard --resource piotroski --force` and commit the JSON.
- Binding moved the dashboard into the bundle folder, which forces a re-create: the dev dashboard got a new ID and URL on the first deploy (2026-10-19). Deploys after that update it in place.
- The prod warehouse lookup runs as the service principal, which needs *Can use* on the warehouse. That grant is a one-off workspace setting, like the catalog bootstrap (ADR-003).
- The generated JSON holds no workspace ID, host or email (checked 2026-10-19). Dashboard URLs carry the workspace ID (`?o=` / `?w=`), so they never go in the README.
