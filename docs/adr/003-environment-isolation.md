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
- The landing volume is `<catalog>.bronze.landing`. Path layout: `/Volumes/<catalog>/bronze/landing/<source>/ingest_date=YYYY-MM-DD/`. The sources are `esef`, `lei_isin` and `exchange_listing`.
- Catalogs are created with `CREATE CATALOG IF NOT EXISTS` in SQL, never in the UI. The statement is sent from the CLI through the Statement Execution API: `databricks api post /api/2.0/sql/statements --json '{"warehouse_id": "<id>", "statement": "CREATE CATALOG IF NOT EXISTS piotroski_dev"}'`. `databricks warehouses list` gives the warehouse id. Do not commit the id. Schemas and the volume move into `databricks.yml` on Day 3, with the catalog name as a per-target variable.
- `piotroski_dev` was created on 2026-10-16. `piotroski_prod` is created the same way before the first prod deploy (Day 6).

## Alternatives considered

- **One catalog, schema prefixes** (`piotroski.dev_bronze`, `piotroski.prod_bronze`). It needs only one catalog. The cost is that dev and prod share one namespace and one set of catalog-level grants. Table names also differ by target, so the pipeline code needs the prefix everywhere.
- **Create catalogs in the UI with Default Storage.** This is what the error message suggests. It breaks the definition of done ("nothing is created by hand in the UI").
- **REST API with `MANAGED LOCATION`.** Free Edition gives no external location or storage credential to point at.

## Consequences

- Isolation is the catalog name only. The same pipeline code runs in both targets with a different `catalog` variable.
- One step sits outside the bundle: the `CREATE CATALOG` statement. It is idempotent and recorded here.
- Day 3: check whether the bundle `catalogs` resource works on Free Edition. It probably calls the same REST API and fails with the same error. If it fails, keep the SQL bootstrap and record that here.
- The upload script takes the catalog as an argument (default `piotroski_dev`).
