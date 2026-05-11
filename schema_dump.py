"""
schema_dump.py — emit a portable schema.sql snapshot of the live database.

Why this exists: 0001_baseline_2026-05-08.sql is a marker, not actual DDL.
The pre-baseline tables (subscribers, treasury_companies, confirmed_purchases,
leaderboard_snapshots, edgar_filings, verification_codes, etc.) live only
inside Supabase. If Supabase has a bad day or someone fat-fingers DROP TABLE,
the schema is unrecoverable from version control alone.

This script connects via DATABASE_URL (same env var as migration_runner.py),
introspects every table in the `public` schema using information_schema +
pg_catalog, and emits a CREATE TABLE / CREATE INDEX SQL file that can be
piped into `psql` to recreate the schema in a fresh database.

Usage:
    DATABASE_URL=postgres://… python schema_dump.py > schema/schema.sql

What it captures:
    - Every table in public schema (including pre-baseline ones)
    - Columns: name, type, default, NOT NULL
    - Primary keys
    - Foreign keys
    - Unique constraints
    - Check constraints
    - Indexes (including partial indexes, expression indexes)

What it does NOT capture (yet — feel free to extend):
    - Row-level security (RLS) policies — Supabase-specific, use
      `pg_policies` view if you need them
    - Triggers — typically only Supabase auth-internal
    - Sequences (auto-handled by pg_catalog when the col is SERIAL/BIGSERIAL)
    - Views, materialized views — none in our schema today
    - Extensions — Supabase enables uuid-ossp + pgcrypto by default

For the production-grade alternative, install psql tools and run:
    pg_dump --schema-only --no-owner --no-privileges $DATABASE_URL > schema/schema.sql

That captures everything. This script is the no-install fallback.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()


def die(msg: str, code: int = 1):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def connect():
    if not DATABASE_URL:
        die(
            "DATABASE_URL not set. Get the Postgres connection string from "
            "Supabase Dashboard → Settings → Database → Connection string → URI, "
            "and either export it or put it in .env."
        )
    try:
        import psycopg2
    except ImportError:
        die("psycopg2 not installed. Run: pip install psycopg2-binary")
    return psycopg2.connect(DATABASE_URL)


# ─────────────────────────── introspection queries ──────────────────────


TABLES_Q = """
SELECT c.relname AS table_name
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind = 'r'                -- ordinary tables only
  AND n.nspname = 'public'
  AND c.relname NOT LIKE 'pg_%'
  AND c.relname NOT IN ('schema_migrations')  -- migration meta — keep separate
ORDER BY c.relname;
"""

COLUMNS_Q = """
SELECT
  a.attname AS column_name,
  pg_catalog.format_type(a.atttypid, a.atttypmod) AS data_type,
  a.attnotnull AS not_null,
  pg_get_expr(d.adbin, d.adrelid) AS column_default,
  a.attnum AS ordinal
FROM pg_attribute a
LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
WHERE a.attrelid = %s::regclass
  AND a.attnum > 0
  AND NOT a.attisdropped
ORDER BY a.attnum;
"""

CONSTRAINTS_Q = """
SELECT
  conname AS constraint_name,
  contype AS constraint_type,             -- p = primary, f = foreign, u = unique, c = check
  pg_get_constraintdef(oid) AS definition
FROM pg_constraint
WHERE conrelid = %s::regclass
ORDER BY contype, conname;
"""

INDEXES_Q = """
SELECT
  i.relname AS index_name,
  pg_get_indexdef(i.oid) AS definition,
  ix.indisprimary AS is_primary,
  ix.indisunique AS is_unique
FROM pg_index ix
JOIN pg_class i ON i.oid = ix.indexrelid
WHERE ix.indrelid = %s::regclass
ORDER BY i.relname;
"""


# ─────────────────────────── DDL composition ─────────────────────────────


def compose_create_table(cur, table_name: str) -> str:
    cur.execute(COLUMNS_Q, (table_name,))
    cols = cur.fetchall()
    if not cols:
        return ""

    col_lines = []
    for col_name, data_type, not_null, default, _ord in cols:
        line = f"  {quote_ident(col_name)} {data_type}"
        if default is not None:
            line += f" DEFAULT {default}"
        if not_null:
            line += " NOT NULL"
        col_lines.append(line)

    # Inline PRIMARY KEY + UNIQUE + CHECK constraints (foreign keys go after
    # all tables exist so we don't hit ordering issues).
    cur.execute(CONSTRAINTS_Q, (table_name,))
    inline_constraints = []
    for con_name, con_type, definition in cur.fetchall():
        if con_type in (b"p", b"u", b"c") or con_type in ("p", "u", "c"):
            inline_constraints.append(f"  CONSTRAINT {quote_ident(con_name)} {definition}")

    body = ",\n".join(col_lines + inline_constraints)
    return f"CREATE TABLE IF NOT EXISTS {quote_ident(table_name)} (\n{body}\n);"


def compose_indexes(cur, table_name: str) -> list[str]:
    cur.execute(INDEXES_Q, (table_name,))
    out = []
    for idx_name, definition, is_primary, is_unique in cur.fetchall():
        if is_primary:
            # Primary key indexes are emitted as inline constraints by Postgres,
            # so we'd be duplicating. Skip.
            continue
        # pg_get_indexdef returns 'CREATE [UNIQUE] INDEX … ON …' — replace
        # 'CREATE INDEX' with 'CREATE INDEX IF NOT EXISTS' for idempotent re-apply.
        if definition.startswith("CREATE UNIQUE INDEX"):
            definition = definition.replace(
                "CREATE UNIQUE INDEX", "CREATE UNIQUE INDEX IF NOT EXISTS", 1
            )
        elif definition.startswith("CREATE INDEX"):
            definition = definition.replace("CREATE INDEX", "CREATE INDEX IF NOT EXISTS", 1)
        out.append(definition + ";")
    return out


def compose_foreign_keys(cur, table_name: str) -> list[str]:
    cur.execute(CONSTRAINTS_Q, (table_name,))
    out = []
    for con_name, con_type, definition in cur.fetchall():
        ctype = con_type.decode() if isinstance(con_type, bytes) else con_type
        if ctype == "f":
            out.append(
                f"ALTER TABLE {quote_ident(table_name)} "
                f"ADD CONSTRAINT {quote_ident(con_name)} {definition};"
            )
    return out


def quote_ident(name: str) -> str:
    """Conservative identifier quoting — wrap in double quotes if it has anything
    other than a-z, 0-9, underscore, or starts with a digit."""
    safe = name.replace('"', '""')
    if name.isidentifier() and not name[0].isdigit() and name == name.lower():
        return name
    return f'"{safe}"'


# ─────────────────────────── main ────────────────────────────────────────


def main():
    conn = connect()
    out = sys.stdout

    out.write(f"-- schema.sql\n")
    out.write(f"-- Auto-generated from live database via schema_dump.py\n")
    out.write(f"-- Generated at: {datetime.utcnow().isoformat()}Z\n")
    out.write(f"-- DO NOT EDIT BY HAND. Re-run schema_dump.py after schema changes.\n")
    out.write(f"--\n")
    out.write(f"-- This file captures the CURRENT state of the public schema. Use it to:\n")
    out.write(f"--   - Recreate the database from scratch (psql DATABASE_URL < schema.sql)\n")
    out.write(f"--   - Review schema diffs in PRs (regen this file alongside any DDL change)\n")
    out.write(f"--   - Bootstrap a staging / test environment\n")
    out.write(f"--\n")
    out.write(f"-- Things this script does NOT capture (extend if you need them):\n")
    out.write(f"--   - Row-level security (RLS) policies (Supabase-specific; query pg_policies)\n")
    out.write(f"--   - Triggers (typically Supabase auth-internal)\n")
    out.write(f"--   - Extensions (uuid-ossp + pgcrypto are Supabase defaults)\n\n")

    out.write(
        '-- Required extensions (Supabase enables these by default, repeated here\n'
        '-- so a fresh non-Supabase Postgres works too).\n'
        'CREATE EXTENSION IF NOT EXISTS "uuid-ossp";\n'
        'CREATE EXTENSION IF NOT EXISTS "pgcrypto";\n\n'
    )

    try:
        with conn.cursor() as cur:
            # 1. List all public tables
            cur.execute(TABLES_Q)
            tables = [row[0] for row in cur.fetchall()]
            print(f"-- Found {len(tables)} table(s) in public schema\n", file=sys.stderr)

            # 2. Emit CREATE TABLE for each (no FK inline — done after)
            for tbl in tables:
                out.write(f"\n-- ─── Table: {tbl} ───────────────────────────────────────────\n")
                ddl = compose_create_table(cur, tbl)
                if ddl:
                    out.write(ddl + "\n\n")
                else:
                    out.write(f"-- (no columns found — skipped)\n\n")

                idx_ddl = compose_indexes(cur, tbl)
                for idx in idx_ddl:
                    out.write(idx + "\n")
                if idx_ddl:
                    out.write("\n")

            # 3. Emit FK constraints AFTER all tables exist
            out.write(f"\n-- ─── Foreign keys ─────────────────────────────────────────────\n")
            any_fk = False
            for tbl in tables:
                for fk in compose_foreign_keys(cur, tbl):
                    out.write(fk + "\n")
                    any_fk = True
            if not any_fk:
                out.write("-- (no foreign keys defined)\n")

            out.write(f"\n-- End of schema.sql ({len(tables)} tables)\n")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
