# ADR-004: Bronze stores raw xBRL-JSON as text; parsing happens in silver

Status: accepted (2026-10-16)

## Context

Each ESEF filing lands as one xBRL-JSON file under `/Volumes/<catalog>/bronze/landing/esef/ingest_date=YYYY-MM-DD/`. Facts are a JSON object keyed by fact id (`{"facts": {"f1": {...}, "f2": {...}}}`), with thousands of distinct keys per file and different keys in every file.

Schema inference on that (Auto Loader `cloudFiles.format = json`, or `spark.read.json`) turns every fact id into a struct field. The schema grows into thousands of columns, changes with every new file, and triggers constant schema evolution.

File sizes in the first load (866 files, 2026-10-16): minimum 7.5 KB, median 111 KB, maximum 11.4 MB. That is well within what one string cell holds.

## Decision

- `bronze.esef_filing_raw` is a streaming table fed by Auto Loader with `cloudFiles.format = text` and `wholetext = true`: **one row per file**, with the whole document in `raw_json`.
- Lineage columns: `source_file` (`_metadata.file_path`), `ingest_date` (parsed from the `ingest_date=` folder name), and `ingested_at` (processing time).
- `pathGlobFilter = *.json` skips `manifest.jsonl` in the same folder.
- No parsing in bronze. Silver parses `raw_json` with `from_json` and an explicit schema (`MAP<STRING, STRUCT<...>>` for facts), so the schema is chosen, not inferred.
- The CSV sources (`lei_isin`, `isin_listing`) also use Auto Loader in bronze, with every column as string and `_rescued_data` kept. Types are set in silver.

## Alternatives considered

- **Auto Loader JSON with schema inference.** Rejected: thousands of columns, plus schema drift on every file.
- **JSON with a fixed schema in bronze.** It works, but bronze is then no longer "what landed". A schema mistake drops data before anyone sees it, and fixing it needs a full re-ingest from the volume.
- **`binaryFile` format.** It keeps the exact bytes, but every reader then has to decode them. Text is just as raw for UTF-8 JSON and easier to inspect.
- **Parse in the extractor and land Parquet.** It moves logic outside Databricks and hides it from pipeline lineage and expectations.

## Consequences

- Bronze is replayable: silver can be rebuilt from bronze with a new schema, without touching the volume or the source APIs.
- Re-running is idempotent. The Auto Loader checkpoint skips files already ingested (second run: no new table version).
- One file is one cell. Spark's single-value limit is about 2 GB, and `from_json` memory grows with file size. If filings ever reach hundreds of MB, revisit this (parse in the extractor, or the `multiLine` JSON reader).
- Do not `display()` `raw_json` in notebooks. Select `length(raw_json)` or a substring.
- Adding a column to a bronze streaming table later only fills new rows. Existing rows stay null until a full refresh. The lineage columns were added on the first deploy for that reason.
