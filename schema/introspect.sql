-- introspect.sql
--
-- Three queries to capture the live schema. Paste each block into
-- Supabase Dashboard → SQL Editor → Run, one at a time. Copy each
-- result column into schema/schema.sql in order: tables first,
-- then constraints, then indexes.
--
-- Why three queries (not one with UNION ALL): the Supabase SQL editor
-- occasionally chokes on multi-shape UNION ALL queries with mixed
-- aggregate / non-aggregate selects. Running them separately is
-- bulletproof.
--
-- IMPORTANT: open this file locally and copy from it directly. If you
-- copy from rendered Markdown / chat UI, single quotes can get smart-
-- quoted (' → ' or '), which makes Postgres parse the rest of the
-- string as bare SQL — you'll see "ERROR: relation \"IF\" does not exist".


-- ───────────────────────── Query 1 — CREATE TABLE ─────────────────────────
-- Run this first. Result: one row per public table, each containing the
-- full CREATE TABLE statement.

SELECT
  'CREATE TABLE IF NOT EXISTS ' || quote_ident(c.relname) || ' (' || chr(10) || '  ' ||
  string_agg(
    quote_ident(a.attname) || ' ' ||
    pg_catalog.format_type(a.atttypid, a.atttypmod) ||
    COALESCE(' DEFAULT ' || pg_get_expr(d.adbin, d.adrelid), '') ||
    CASE WHEN a.attnotnull THEN ' NOT NULL' ELSE '' END,
    ',' || chr(10) || '  '
    ORDER BY a.attnum
  ) || chr(10) || ');' AS ddl
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
WHERE c.relkind = 'r'
  AND n.nspname = 'public'
  AND c.relname != 'schema_migrations'
GROUP BY c.relname
ORDER BY c.relname;


-- ───────────────────────── Query 2 — constraints ──────────────────────────
-- Primary keys, foreign keys, unique constraints, check constraints.
-- Run after Query 1 and append the results to schema/schema.sql.

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


-- ───────────────────────── Query 3 — indexes ──────────────────────────────
-- All secondary indexes (primary key indexes are auto-created by Postgres
-- so we skip them). Run last and append to schema/schema.sql.

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
