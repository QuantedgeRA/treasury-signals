-- 0001_baseline_2026-05-08.sql
--
-- Baseline marker for the migration system. No DDL.
--
-- All schema in the Supabase project as of 2026-05-08 was applied directly
-- via the Supabase SQL editor or supabase-py inserts, with no version control
-- record. This file establishes the starting point: from here forward, every
-- schema change lives in this folder before it lives in production.
--
-- The pre-baseline tables (treasury_companies, confirmed_purchases,
-- pending_purchases, confirmed_sales, edgar_filings, subscribers,
-- leaderboard_snapshots, etc.) are NOT defined here. To recreate them in a
-- fresh environment, currently you must either:
--   (a) restore from a Supabase backup, or
--   (b) connect to the live DB and run pg_dump --schema-only.
--
-- A future phase 3b migration will replace this marker with the full
-- pg_dump of the baseline schema, making the project reproducible from
-- scratch. Until then, this file's only job is to anchor the version chain.

DO $$ BEGIN
  RAISE NOTICE 'Baseline migration 0001 applied — schema versioning starts here';
END $$;
