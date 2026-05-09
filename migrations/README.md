# Database migrations

Tracked, versioned schema changes for the TSI Supabase database.

## The convention

- One `.sql` file per change, named `NNNN_short_description.sql` (zero-padded).
- Always **idempotent** — use `IF NOT EXISTS`, `IF EXISTS`, `CREATE OR REPLACE`. Migrations may be re-run; they should not fail or duplicate state.
- One concern per file. Don't bundle "add column + new table + index drop" — split them.
- Migrations are **append-only**. Never edit a file once it's been applied. To revert or change something, write a new migration.

## Applying migrations

```bash
# Show what's applied vs pending
python migration_runner.py status

# Apply all pending migrations
python migration_runner.py apply

# Show the SQL of a specific migration without running it
python migration_runner.py show 0002
```

Two execution modes (auto-detected):

1. **Auto-apply (preferred)** — when `DATABASE_URL` env var is set, the runner executes SQL directly via psycopg2. This is what you want once you've grabbed the Postgres connection string from Supabase → Settings → Database.

2. **Manual fallback** — when `DATABASE_URL` is unset, the runner prints the SQL of pending migrations and asks you to run them yourself in the Supabase SQL editor, then run `python migration_runner.py mark-applied <version>` to record application. Use this for one-off DDL until you're ready to wire up `DATABASE_URL`.

State is tracked in a `schema_migrations(version, applied_at, checksum)` table that the runner self-bootstraps on first run.

## Adding a new migration

1. Write the next-numbered `.sql` file. Bump the version: `ls migrations/*.sql | tail -1` and add 1.
2. Make it idempotent. Test by running it twice — the second run should be a no-op.
3. `python migration_runner.py status` shows it as pending.
4. `python migration_runner.py apply` (or run manually + mark-applied).
5. Commit the new SQL file with the same PR as any code that depends on the schema change.

## Why this exists

Before this folder, schema changes happened in the Supabase SQL editor with nothing in git tracking what was applied. On 2026-05-08 we discovered `edgar_filings.source` was missing for 28+ days because the column existed in code but not in the table — caught only by a manual query that errored. The migration runner makes this class of bug impossible: any schema delta lives in version control before it lives in production.

## Limitations (current MVP scope)

- No down-migrations / rollbacks. To undo, write a forward migration.
- No automated schema dump of pre-existing state. `0001_baseline_2026-05-08.sql` is a marker, not a `CREATE TABLE` dump. To bootstrap a new env, you currently need the live DB. A `pg_dump` of the existing schema is a future "phase 3b" task.
- No checksum verification (yet). A future enhancement could detect if a migration file was edited after being applied.
