-- 0013_add_direction.sql
--
-- Direction-aware classifier (pipelines/direction_classifier.py) tags BTC
-- treasury 8-Ks as pure_buy / raise_then_buy / convertible / sale / unclear.
-- This migration adds the persistence columns so:
--
--   1. edgar_realtime.py writes direction + direction_confidence on every
--      new filing it processes through the reconciler.
--   2. The proof page (and future /filings filter) can aggregate by
--      direction to surface "pure buys averaged +X%, raise-then-buy
--      averaged -Y%" — the trader-led framing the /proof page hinted at.
--   3. Backfill scripts can classify the existing confirmed_purchases
--      history retroactively.
--
-- Direction is a property of the FILING TEXT, not the company or ticker,
-- so it lives on both edgar_filings (live ingest) and confirmed_purchases
-- (deduplicated historical record).
--
-- Both columns are nullable: legacy rows have NULL direction until the
-- backfill runs; the classifier may legitimately return 'unclear' (stored
-- as the string, not NULL — NULL means "not yet classified").

ALTER TABLE public.edgar_filings
  ADD COLUMN IF NOT EXISTS direction TEXT,
  ADD COLUMN IF NOT EXISTS direction_confidence SMALLINT;

ALTER TABLE public.confirmed_purchases
  ADD COLUMN IF NOT EXISTS direction TEXT,
  ADD COLUMN IF NOT EXISTS direction_confidence SMALLINT;

-- Partial index for the /proof page aggregation query
-- ("avg move per direction" — only rows where direction is set).
CREATE INDEX IF NOT EXISTS idx_confirmed_purchases_direction
  ON public.confirmed_purchases (direction)
  WHERE direction IS NOT NULL;
