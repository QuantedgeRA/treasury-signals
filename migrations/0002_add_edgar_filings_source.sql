-- 0002_add_edgar_filings_source.sql
--
-- Add the `source` column to edgar_filings.
--
-- Background: global_filing_scanner.py and edgar_realtime.py adapters all
-- include a 'source' field in their upsert payloads (e.g., 'SEC EDGAR (USA)',
-- 'Google News [ja-JP]', 'CoinDesk'). The column was missing from the table
-- schema for 28+ days, causing every upsert from those paths to fail silently
-- (the exception was swallowed by `logger.debug`). edgar_filings was empty
-- as a result; only news/atom paths surfaced filings, and only after the
-- column was added.
--
-- This ALTER was applied manually to the live Supabase on 2026-05-08 via the
-- SQL editor. This file captures that change so it's reproducible. Idempotent
-- via IF NOT EXISTS, so re-running against the live DB is a no-op.

ALTER TABLE edgar_filings ADD COLUMN IF NOT EXISTS source TEXT;
