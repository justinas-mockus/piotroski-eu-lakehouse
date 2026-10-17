# ADR-010: Ship `src/piotroski` to the pipeline as a versioned wheel

Status: accepted (2026-10-17)

## Context

Business logic lives in `src/piotroski/` as `DataFrame -> DataFrame` functions, and the pipeline files only wire them (house rules). Bundle-deployed pipeline source files don't see `src/` on their Python path (found on Day 3), so the package has to reach the serverless pipeline some other way.

On Day 4, a fix to `src/piotroski/fundamentals.py` passed the unit tests but didn't change `silver.fundamentals`, even after a full refresh. The event log (`user_code_context.python_environment`) showed what each update had installed:

- Every update ran `piotroski-eu-lakehouse 0.1.0`, with the same `environment_sha256`. That held after redeploying a rebuilt 0.1.0 wheel, after bumping to 0.1.1 and 0.1.2 (the pipeline settings showed the new path), and after `databricks pipelines stop`.
- `dynamic_version: true` on the bundle artifact built and uploaded a timestamped wheel (`0.1.0+<timestamp>`), but the pipeline's `environment.dependencies` kept pointing at the plain wheel. In CLI v1.21.0, the rewrite reaches job libraries, not pipelines.
- The cause was development mode. `mode: development` makes pipelines `development: true`, and a development pipeline reuses its warm compute, environment included. Switching the pipeline to production mode for one run installed 0.1.2 and changed the table (1134 rows to 815).
- Setting `development: false` on the pipeline resource has no effect under `mode: development`, and the CLI flags the property as deprecated. The bundle preset `pipelines_development: false` does work.

## Decision

1. `pyproject.toml` builds a wheel with hatchling. The bundle artifact `piotroski_wheel` runs `uv build --wheel`, and the pipeline installs it through `environment.dependencies: [../dist/*.whl]`.
2. The `dev` target keeps `mode: development` (name prefix, paused schedules) with `presets: pipelines_development: false`, so each update starts fresh compute and installs the current wheel.
3. Every change to `src/` that gets deployed bumps the version in `pyproject.toml`. A new version is a new file name and dependency path, so a cached environment can't be reused by mistake. Remove the old wheel first (`rm dist/*.whl`): the glob would match both.
4. To confirm which code ran, read the installed version from the event log, not the pipeline settings:

   ```sql
   SELECT timestamp,
          filter(from_json(details:user_code_context.python_environment.installed_libraries,
                           'ARRAY<STRUCT<name STRING, version STRING>>'),
                 l -> l.name LIKE 'piotroski%') AS lib
   FROM event_log(TABLE(piotroski_dev.silver.fundamentals))
   WHERE event_type = 'user_code_context'
   ORDER BY timestamp DESC LIMIT 1
   ```

## Alternatives considered

- **`dynamic_version: true`.** Automatic and timestamped, but it doesn't reach pipeline environments (above).
- **Keep development mode and switch to production for one run after each `src/` change.** It needs no config, but it's a manual step, and forgetting it fails silently: the run is green with old code.
- **Put the synced `src/` folder on `sys.path` in the pipeline files.** No wheel and no version bumps, but the pipeline files then carry path setup, and the code that runs is no longer a versioned artifact.
- **Upload the wheel to a volume and reference it by `/Volumes/...` path.** This was the Step 1 fallback. The path is a different place to store the file, so it wouldn't fix the environment reuse.

## Consequences

- Updates start slower: each one starts compute and installs the environment.
- The version bump is manual until Day 6 CI. A stale run is still possible if a bump is forgotten, and the event-log check catches it.
- Free Edition allows only a few serverless computes at once. With the pipeline, a notebook and a SQL warehouse running, starting a fresh pipeline compute failed with `CLUSTER_CREATION_RESOURCE_EXHAUSTED`. Stop the warehouse and detach notebooks before a run.
- `databricks bundle validate` is clean. The deprecated `development` property is not used.
