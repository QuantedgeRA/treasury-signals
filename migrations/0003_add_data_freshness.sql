-- 0003_add_data_freshness.sql
--
-- Create the `data_freshness` table referenced by freshness_tracker.py.
--
-- The SETUP_SQL constant at freshness_tracker.py:484-499 has lived as a
-- docstring asking the operator to "run this in your Supabase SQL Editor".
-- Whether it was actually applied is unknown until you run this migration:
-- if the table already exists, IF NOT EXISTS makes this a no-op; if it
-- doesn't, this migration creates it.
--
-- The table powers the data-freshness widget on the dashboard (freshness
-- per source, with ages and last-error). save_to_supabase() upserts here
-- on every scan cycle.

CREATE TABLE IF NOT EXISTS data_freshness (
    id BIGSERIAL PRIMARY KEY,
    snapshot_time TIMESTAMP WITH TIME ZONE UNIQUE NOT NULL,
    overall_health TEXT DEFAULT 'unknown',
    live_count INTEGER DEFAULT 0,
    stale_count INTEGER DEFAULT 0,
    unavailable_count INTEGER DEFAULT 0,
    sources_json JSONB DEFAULT '[]'::jsonb,
    provenance_json JSONB DEFAULT '{}'::jsonb
);
