-- 0023_edgar_acceptance_datetime.sql
--
-- Make SEC filing -> alert latency measurable.
--
-- The product markets "real-time" / "sub-60-second" 8-K alerts, but until now
-- nothing captured WHEN the SEC actually accepted a filing, so true
-- file->alert latency was unmeasurable and the claim unverifiable (see
-- [[edgar-filing-path-broken]]). EFTS hits carry only file_date (a calendar
-- day, no time); the real acceptance timestamp comes from the EDGAR getcurrent
-- Atom feed (<updated>) and the data.sec.gov submissions API (acceptanceDateTime).
--
-- This adds:
--   acceptance_datetime  — when the SEC accepted the filing (UTC, from EDGAR)
--   alerted_at           — when our pipeline sent the alert (UTC)
-- The difference is the file->alert latency. Both nullable + backfillable; the
-- scanners populate them best-effort and degrade gracefully if absent.
--
-- Apply manually in the Supabase SQL editor (DATABASE_URL is unset in this
-- project, same as 0022). Idempotent — safe to re-run.

ALTER TABLE edgar_filings
    ADD COLUMN IF NOT EXISTS acceptance_datetime timestamptz,
    ADD COLUMN IF NOT EXISTS alerted_at          timestamptz;

-- Fast lookup of the most recent real SEC filings by acceptance time
-- (the latency dashboard / freshness checks read this ordering).
CREATE INDEX IF NOT EXISTS idx_edgar_filings_acceptance
    ON edgar_filings (acceptance_datetime DESC)
    WHERE acceptance_datetime IS NOT NULL;
