# ADR-003: One Unity Catalog catalog per target

Status: accepted (2026-10-16)

## Context

The bundle has two targets, `dev` and `prod`, deployed to the same Free Edition workspace. Each needs its own landing volume and its own bronze, silver and gold tables, so a dev run can never overwrite prod data. Day 2 needs the landing volume path, so the naming is decided now, not on Day 3.

Creating a catalog through the REST API fails:

```
$ databricks catalogs create piotroski_dev
Error: Metastore storage root URL does not exist. Default Storage is enabled in your account.
You can use the UI to create a new catalog using Default Storage, or please provide a storage
location for the catalog (for example 'CREATE CATALOG myCatalog MANAGED LOCATION '<location-path>').
```

The same operation in SQL on the serverless warehouse succeeds and uses Default Storage:

```sql
CREATE CATALOG IF NOT EXISTS piotroski_dev
```

Schemas and volumes inside that catalog can be created with the CLI (`databricks schemas create`, `databricks volumes create`).

## Decision

- One catalog per target: `piotroski_dev` and `piotroski_prod`. Inside each catalog, the schemas have the same names: `bronze`, `silver`, `gold`.
- The landing volume is `<catalog>.bronze.landing`. Path layout: `/Volumes/<catalog>/bronze/landing/<source>/ingest_date=YYYY-MM-DD/`. The sources are `esef`, `lei_isin` and `openfigi` (ADR-008; `exchange_listing` holds the dropped Nasdaq screener export).
- Catalogs are created with `CREATE CATALOG IF NOT EXISTS` in SQL, never in the UI. The statement is sent from the CLI through the Statement Execution API: `databricks api post /api/2.0/sql/statements --json '{"warehouse_id": "<id>", "statement": "CREATE CATALOG IF NOT EXISTS piotroski_dev"}'`. `databricks warehouses list` gives the warehouse id. Do not commit the id. Schemas and the volume move into `databricks.yml` on Day 6 (see Consequences); the catalog name is already a per-target variable.
- `piotroski_dev` was created on 2026-10-16. `piotroski_prod` is created the same way before the first prod deploy (Day 6).

## Alternatives considered

- **One catalog, schema prefixes** (`piotroski.dev_bronze`, `piotroski.prod_bronze`). It needs only one catalog. The cost is that dev and prod share one namespace and one set of catalog-level grants. Table names also differ by target, so the pipeline code needs the prefix everywhere.
- **Create catalogs in the UI with Default Storage.** This is what the error message suggests. It breaks the definition of done ("nothing is created by hand in the UI").
- **REST API with `MANAGED LOCATION`.** Free Edition gives no external location or storage credential to point at.

## Consequences

- Isolation is the catalog name only. The same pipeline code runs in both targets with a different `catalog` variable.
- One step sits outside the bundle: the `CREATE CATALOG` statement. It is idempotent and recorded here.
- Day 3 check (2026-10-16): the bundle `catalogs` resource calls the same REST API and fails the same way. The SQL bootstrap stays. Dev mode does not prefix catalog names (`validate -o json` showed `piotroski_probe` unchanged).

  ```text
  $ databricks bundle deploy -t dev
  Error: cannot create resources.catalogs.probe: Metastore storage root URL does not exist.
  Default Storage is enabled in your account. [...] (400 INVALID_STATE)
  Endpoint: POST https://<workspace>/api/2.1/unity-catalog/catalogs
  ```

- Day 6 (2026-10-18): the schemas and the landing volume are bundle resources in **prod only** (`resources/schemas.yml`, under `targets.prod`). Development mode prefixes UC schema names (`validate -o json` showed `dev_<user>_bronze`), which would break the pipeline's qualified names (`silver.fact`). So dev keeps its CLI-created schemas and volume, and nothing in dev is bound. In prod, the pipeline's `schema` refers to `${resources.schemas.bronze.name}`, so the deploy creates `bronze` before the pipeline. Every one of these resources has `lifecycle.prevent_destroy: true`: a bundle drops a managed schema, tables included, on `bundle destroy` or when it is removed from the config.
- The prod catalog is still created by the SQL bootstrap (2026-10-18), with `USE CATALOG` and `CREATE SCHEMA` granted to the CI service principal (ADR-006). The service principal owns the schemas and the volume it creates. A person who uploads to the prod volume needs `USE SCHEMA` on `bronze` and `READ VOLUME`/`WRITE VOLUME` on the volume, granted by the catalog owner.
- First prod deploy (2026-10-18): the bundle creates the landing volume in the same deploy that would run the job, so the volume is empty and Auto Loader cannot infer the CSV schemas (`CF_EMPTY_DIR_FOR_SCHEMA_INFERENCE`). `deploy.yml` therefore runs the job only when the repository variable `RUN_AFTER_DEPLOY` is `true`. Bootstrap order: merge (deploy only), grant, `extract/upload_to_volume.sh piotroski_prod`, set the variable, re-run `deploy` with `workflow_dispatch`.
- The upload script takes the catalog as an argument (default `piotroski_dev`).
- Day 4 (2026-10-17): one pipeline (`piotroski_fundamentals`) publishes to all three schemas. Its default schema is `bronze`; silver and gold tables use qualified names (`silver.fact`, `silver.fundamentals`). One pipeline keeps the lineage graph and the expectation counts in one event log, and avoids cross-pipeline scheduling on a workspace capped at a few concurrent serverless computes. The cost is that a full refresh must name its tables (`--full-refresh silver.fundamentals`), or it resets bronze too.
