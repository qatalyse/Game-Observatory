# Database foundation (M1A)

**State:** Schema migrations and smoke tests are committed; no remote Supabase project is modified by committing these files.

## Target project

- Project URL: `https://wazppezuhtkrpgipnqcm.supabase.co`
- Region: Singapore
- Remote linking and deployment: **not authorized in M1A**.

## Local prerequisites

Install Docker, PostgreSQL `psql`, and the Supabase CLI. Use a supported local Supabase CLI version; check that the local database PostgreSQL major version matches the remote project before running migrations. The version in `supabase/config.toml` is a local starting default, **not a claim about the remote version**.

From repository root:

```sh
supabase start
supabase db reset --local
psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" \
  -X -v ON_ERROR_STOP=1 -f supabase/tests/001_schema_smoke.sql
supabase stop
```

The smoke test runs inside `BEGIN ... ROLLBACK`; fixtures are not persisted. Default local credentials above are the standard *local development* database values; never use them for a remote environment.

## Structure

1. `20261117000100_foundation.sql`: `core`, `raw`, `ops`, `analytics` schemas; country dimension; canonical game identity; store listings; market association; collection runs.
2. `20261117000200_apple.sql`: Apple ranking snapshots and entries; country-specific app metadata.
3. `20261117000300_steam.sql`: Steam player counts, achievement definitions and snapshots, current review records.
4. `20261117000400_analytics.sql`: security-invoker analytical views for Apple rank history, Steam sampled concurrency, review trends, and achievement trends.

All collection timestamps are `timestamptz`. Collectors must store UTC observations, independently record run times, and validate source data before opening a write transaction.

## Data semantics

- Apple source rank is preserved. `complete`/ `partial` status must be established by feed validation, not inferred from nonempty data alone.
- Missing records in a Top-N chart are **not** zero downloads or sales.
- `previous_observed_rank` skips observations where a listing was not present. Chart entry/exit calculations must join against the full snapshot calendar and coverage before being added.
- `highest_sampled_players` is the maximum collected measurement, **not** the actual Steam daily peak.
- Reviews store latest observed record only; edits are not versioned in M1A.
- A source app ID is not proof of cross-store game identity. `core.store_listings.game_id` is optional pending verification.
- Application code must validate that Apple entries reference Apple listings, Steam records reference Steam listings, and markets match allowed combinations. The current schema doesn't enforce these cross-table source invariants via triggers.
- The Apple snapshot `entry_count` is declared by the collector. An application transaction must verify that committed entries match it. An empty/error response is logged in `ops.collection_runs`, not invented as a successful ranking.
- Collection runs may group multiple achievement snapshots; retries must use deterministic keys and conflict-aware inserts.

## Security

The four application schemas are not listed in the local Data API exposed schemas. Explicit schema and object grants to `anon` and `authenticated` are revoked. Analytical views use `security_invoker = true`, so read access requires underlying table privileges too.

This is **deny-by-default scaffolding**, not a completed least-privilege production role configuration. Before remote deployment, create separate collector and analytics roles, audit inherited/default privileges and API-exposed schemas, verify direct role access, and document secret rotation. Do not put privileged Supabase keys or database connection strings in the frontend or repository.

## Remote deployment (NOT YET AUTHORIZED)

When explicitly approved in a later milestone:

1. Inspect the remote PostgreSQL major version, existing schemas, extensions, grants, and migration history.
2. Prepare a backup/restore rehearsal and reconcile any existing schema objects.
3. Review migration SQL for conflicts, and validate in a remote-like test database.
4. Link the specific project only after approval: `supabase link --project-ref wazppezuhtkrpgipnqcm`.
5. Review changes with `supabase db push --dry-run`; apply only after explicit authorization.
6. Run smoke tests using a scoped authorized database role; recheck default privileges and unauthorized role access.
7. Configure least-privilege collectors and scheduled jobs separately in M1B/M2.

**Never execute remote migrations solely because code was committed.**

## Outstanding implementation before collection

- Collector-specific role grants and secret management.
- Source/market referential validation and atomic entry-count verification.
- Retry/idempotency contract for multi-record jobs.
- Broader data quality tests and charts coverage tracking.
- Backup/export and retention procedure.
- PostgreSQL version verification, local migration execution and CI database tests.
