# ADR-006: CI authenticates as a service principal with OAuth M2M

Status: accepted (2026-10-18)

## Context

The definition of done says CI deploys everything: `ci.yml` runs `databricks bundle validate` on every PR, and `deploy.yml` runs `databricks bundle deploy -t prod` and `bundle run` on merge to `main`. Both need credentials for the Free Edition workspace, stored outside the repo. Free Edition has no account console, so it was unclear whether service principals and their OAuth secrets are available at all.

Spike (2026-10-18): a service principal `piotroski-ci` was created in the workspace settings (Identity and access → Service principals), given workspace access, and issued a workspace-level OAuth secret. With only environment variables set and the local profile hidden (`DATABRICKS_CONFIG_FILE=/dev/null`), the CLI authenticated as the service principal:

```text
$ databricks auth describe
User: <application id>
Authenticated with: oauth-m2m
$ databricks current-user me -o json | jq '{displayName, active}'
{ "displayName": "piotroski-ci", "active": true }
```

## Decision

- CI authenticates as the service principal `piotroski-ci` with OAuth machine-to-machine (client ID + client secret). The CLI reads `DATABRICKS_HOST`, `DATABRICKS_CLIENT_ID` and `DATABRICKS_CLIENT_SECRET` from the environment, with no profile and no login step.
- The OAuth secret scope is `all-apis`. One deploy touches workspace files, jobs, pipelines and Unity Catalog, so a narrower scope fails partway through. Privileges are limited through UC grants on `piotroski_prod` instead (step 3, Day 6).
- Two secrets on the same service principal, so each can be revoked on its own:
  - `github-prod-deploy`: GitHub **environment** `prod`, deployable only from protected branches (`main`). Used by `deploy.yml`.
  - `github-ci-validate`: GitHub **repository** secrets. Used by `ci.yml`. Pull requests from forks don't receive secrets.
- The workspace URL, application ID and secrets live only in GitHub secrets, never in the repo.

## Alternatives considered

- **Personal access token.** It works on Free Edition and needs no setup. But CI would act as a person, the token is long-lived and has full user rights, and every deployed resource would be owned by that user.
- **GitHub OIDC federation (no stored secret).** The best option on paid tiers: short-lived tokens, nothing to rotate. It needs an account-level federation policy, and Free Edition has no account console.
- **Run deploys from the laptop.** That breaks the definition of done ("one command run by CI").

## Consequences

- The secrets expire (lifetime set at creation; the expiry date is in the service principal's Secrets tab). Rotation: generate a new secret, `gh secret set DATABRICKS_CLIENT_SECRET [--env prod]`, revoke the old one. An expired secret shows up as an `invalid_client` failure in CI.
- Prod resources are deployed by, and run as, `piotroski-ci`, not as a user. On `piotroski_prod` the service principal gets only `USE CATALOG` and `CREATE SCHEMA`. The bundle creates the schemas and the landing volume, so the service principal owns them and everything in them. The catalog stays owned by the user who ran `CREATE CATALOG`.
- Both secrets have the same privileges. Splitting them limits blast radius only in the sense of separate revocation. A second service principal for validation only is post-MVP.
