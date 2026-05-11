# Schema in version control

`schema/schema.sql` is the canonical snapshot of the live Supabase schema —
checked into git so the database can be recreated from scratch, schema diffs
show up in PR reviews, and a Supabase outage doesn't lose the data model.

## What's here

| File                   | Purpose                                                                                  |
|------------------------|------------------------------------------------------------------------------------------|
| `schema.sql`           | The current schema snapshot. **Regenerated, not hand-edited.**                            |
| `regen.sh` / `regen.ps1` | Regenerates `schema.sql`. Picks the best strategy based on `DATABASE_URL`.              |
| `introspect.sql`       | A pure SQL recipe to paste into Supabase Dashboard → SQL Editor for a one-shot dump.    |

The single source of truth for *changes* is still `migrations/` — every DDL
delta is a numbered `.sql` migration. `schema.sql` is the assembled snapshot.

## Three paths to keep `schema.sql` in sync

Pick whichever fits where you are. They all produce the same artifact.

### Path A — `schema_dump.py` (recommended once `DATABASE_URL` is set)

Live introspection via psycopg2. Captures every table in the public schema
including pre-baseline ones, with constraints and indexes.

```bash
# One-time: get the Postgres connection string from
# Supabase Dashboard → Settings → Database → Connection string → URI
export DATABASE_URL="postgres://postgres:…@db.…supabase.co:5432/postgres"

# Then any time:
python schema_dump.py > schema/schema.sql
# or:
bash schema/regen.sh        # detects DATABASE_URL automatically
```

This is the **best path** — works on any OS, no extra tools beyond
`psycopg2-binary` (already in requirements). Re-run whenever schema changes.

### Path B — `pg_dump` (gold standard, requires psql client tools installed)

If/when you install PostgreSQL client tools (Windows: from postgresql.org;
Mac: `brew install libpq`; Linux: `apt-get install postgresql-client`):

```bash
pg_dump --schema-only --no-owner --no-privileges "$DATABASE_URL" \
  > schema/schema.sql
```

This captures everything Path A captures, plus row-level security policies,
triggers, sequences, and view definitions. Use it when you start needing RLS.

### Path C — Supabase SQL Editor (no install at all)

For when you can't set `DATABASE_URL` locally yet but have dashboard access:

1. Open Supabase Dashboard → SQL Editor
2. Paste the contents of `schema/introspect.sql`
3. Run
4. Copy the result column into `schema/schema.sql` (overwriting the file)
5. Commit

Slowest path but works on any machine with a browser. Use it as a one-time
bootstrap to capture pre-baseline tables; switch to Path A or B for
ongoing maintenance.

## When to regenerate

After any of these:
- Adding a migration (`migrations/00NN_*.sql`)
- A manual schema change in the Supabase dashboard (try to avoid these — write a migration instead)
- Adding RLS policies, triggers, or extensions

Drop the regenerated `schema.sql` into the same PR as the change. Reviewers
see both the migration delta and the post-change full snapshot.

## When to recover from `schema.sql`

To recreate the database from scratch (new Supabase project, staging env,
local Postgres for testing):

```bash
psql "$DATABASE_URL" < schema/schema.sql
```

The file is idempotent (`CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT
EXISTS`) so re-running on an existing database is safe — it'll add anything
missing and skip what's there.

## What this doesn't replace

- **Migrations are still the source of truth** for development. Always write
  a migration first, then regenerate `schema.sql` after it's applied.
- **Backups are still the source of truth** for *data*. `schema.sql` only
  captures structure — tables, columns, indexes, constraints. Use Supabase's
  daily backups (or `pg_dump` without `--schema-only`) for data recovery.
- **RLS policies in Path A's output are missing today.** If you start using
  RLS heavily, switch to Path B (`pg_dump`).

## Current status (2026-05-11)

`schema.sql` now contains **all 22 public tables + columns + defaults + NOT
NULL** captured live from Supabase via the metadata-dump CSV workflow:

1. Paste the data-dump query in `schema/introspect.sql` (the simple one that
   returns column metadata as data, not as DDL strings) into the Supabase
   SQL Editor.
2. Download the result as CSV.
3. Run `python schema/_csv_to_schema.py < your_dump.csv > schema/schema.sql`
   (or update the `EMBEDDED_CSV` constant in `_csv_to_schema.py` and run it
   without stdin).

**Still missing from `schema.sql`:**

- **Constraints** — primary keys, foreign keys, unique constraints, check
  constraints. These exist in the live DB but aren't yet in version control.
- **Indexes** — secondary indexes (B-tree, partial, expression).

**To add them:** open the Supabase SQL Editor and run the constraint +
index queries shown below. Append the results to `schema/schema.sql`
under section headers like `-- ─── CONSTRAINTS ───` and
`-- ─── INDEXES ───`. (These queries are also in `schema/introspect.sql`
as "Query 2" and "Query 3".)

```sql
-- Constraints
SELECT
  'ALTER TABLE ' || quote_ident(rel.relname) ||
  ' ADD CONSTRAINT ' || quote_ident(con.conname) ||
  ' ' || pg_get_constraintdef(con.oid) || ';' AS ddl
FROM pg_constraint con
JOIN pg_class rel ON rel.oid = con.conrelid
JOIN pg_namespace n ON n.oid = rel.relnamespace
WHERE n.nspname = 'public'
  AND rel.relname != 'schema_migrations'
  AND con.contype IN ('p', 'f', 'u', 'c')
ORDER BY rel.relname, con.contype;
```

```sql
-- Indexes
SELECT
  REPLACE(pg_get_indexdef(ix.indexrelid), 'CREATE INDEX', 'CREATE INDEX IF NOT EXISTS') || ';' AS ddl
FROM pg_index ix
JOIN pg_class i ON i.oid = ix.indexrelid
JOIN pg_class t ON t.oid = ix.indrelid
JOIN pg_namespace n ON n.oid = t.relnamespace
WHERE n.nspname = 'public'
  AND t.relname != 'schema_migrations'
  AND NOT ix.indisprimary
ORDER BY t.relname, i.relname;
```

The two follow-ups above can wait — having tables in version control is the
80% of disaster-recovery value. Constraints and indexes can be reconstructed
by re-running the relevant migration files for things we added post-baseline,
and the rest are PKs / sensible indexes a fresh DB rebuild can re-add by
hand. But for full reproducibility, run those two queries and append.

## Future maintenance

Once `DATABASE_URL` is set locally, `schema_dump.py` does everything in one
shot — tables + constraints + indexes — and replaces the CSV-and-Python
workflow. Until then, the embedded CSV in `_csv_to_schema.py` is the
canonical baseline; re-dump and update it on schema changes.
