-- introspect.sql
--
-- Paste this into Supabase Dashboard → SQL Editor → Run.
-- The result is a single column of DDL strings — copy them into
-- schema/baseline.sql to capture the current schema in version control.
--
-- This is the no-install path: works without Supabase CLI, without psql,
-- without setting DATABASE_URL locally. Just the dashboard.
--
-- For the cleaner programmatic path (regeneratable any time you change
-- schema), use schema_dump.py instead — it emits the same shape via
-- psycopg2 + DATABASE_URL.

-- ─────────────────────────── header / meta ─────────────────────────────

SELECT '-- Pasted from Supabase SQL Editor on ' || NOW()::TEXT AS ddl
UNION ALL
SELECT '-- Found ' || COUNT(*)::TEXT || ' table(s) in public schema'
FROM pg_tables WHERE schemaname = 'public'
UNION ALL
SELECT ''
UNION ALL
SELECT 'CREATE EXTENSION IF NOT EXISTS "uuid-ossp";'
UNION ALL
SELECT 'CREATE EXTENSION IF NOT EXISTS "pgcrypto";'
UNION ALL
SELECT ''

-- ─────────────────────────── CREATE TABLE per table ────────────────────
-- Composes CREATE TABLE IF NOT EXISTS for each public table by aggregating
-- columns from pg_attribute. Includes data type, default, NOT NULL.
-- Constraints (PK, FK, UNIQUE) are emitted as separate ALTER TABLE blocks
-- below to avoid ordering issues.
UNION ALL
SELECT
  '-- Table: ' || c.relname AS ddl
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind = 'r' AND n.nspname = 'public' AND c.relname != 'schema_migrations'

UNION ALL
SELECT
  'CREATE TABLE IF NOT EXISTS ' || quote_ident(c.relname) || ' (' || E'\n  ' ||
  string_agg(
    quote_ident(a.attname) || ' ' || pg_catalog.format_type(a.atttypid, a.atttypmod) ||
    COALESCE(' DEFAULT ' || pg_get_expr(d.adbin, d.adrelid), '') ||
    CASE WHEN a.attnotnull THEN ' NOT NULL' ELSE '' END,
    ',' || E'\n  '
    ORDER BY a.attnum
  ) ||
  E'\n);' AS ddl
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
WHERE c.relkind = 'r' AND n.nspname = 'public' AND c.relname != 'schema_migrations'
GROUP BY c.relname

-- ─────────────────────────── constraints (PK, FK, UNIQUE, CHECK) ───────
UNION ALL
SELECT
  'ALTER TABLE ' || quote_ident(rel.relname) || ' ADD CONSTRAINT ' ||
  quote_ident(con.conname) || ' ' || pg_get_constraintdef(con.oid) || ';'
FROM pg_constraint con
JOIN pg_class rel ON rel.oid = con.conrelid
JOIN pg_namespace n ON n.oid = rel.relnamespace
WHERE n.nspname = 'public'
  AND rel.relname != 'schema_migrations'
  AND con.contype IN ('p', 'f', 'u', 'c')

-- ─────────────────────────── indexes (skip PK indexes — auto-created) ──
UNION ALL
SELECT
  REPLACE(
    REPLACE(pg_get_indexdef(ix.indexrelid), 'CREATE UNIQUE INDEX', 'CREATE UNIQUE INDEX IF NOT EXISTS'),
    'CREATE INDEX', 'CREATE INDEX IF NOT EXISTS'
  ) || ';'
FROM pg_index ix
JOIN pg_class i ON i.oid = ix.indexrelid
JOIN pg_class t ON t.oid = ix.indrelid
JOIN pg_namespace n ON n.oid = t.relnamespace
WHERE n.nspname = 'public'
  AND t.relname != 'schema_migrations'
  AND NOT ix.indisprimary;
