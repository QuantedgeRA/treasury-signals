-- 0019_backtest_reactions.sql
--
-- "Trade-the-tape" backtest substrate: pre-computed equity reactions
-- around every confirmed BTC treasury purchase event.
--
-- Why this is a moat-class feature
-- ================================
-- The strategic review at 2026-05-21 (recovered in
-- [[strategic_review_2026_05_21]]) flagged this as "the single most
-- persuasive landing-page asset you could ship." For every confirmed
-- treasury purchase in confirmed_purchases, this table stores the
-- pre/post equity prices and computed % reactions at standard horizons.
-- The /backtest page (lead-gen, public) renders the result as a sortable
-- grid + summary stats — proof that the signal has historical alpha.
--
-- Why a pre-computed table (vs. lazy compute)
-- ===========================================
-- Backtest page load shouldn't trigger ~50 yfinance calls and wait
-- ~10 seconds. Pre-compute via the morning scheduler (1-time backfill
-- via scripts/backfill_backtest_reactions.py for history; ongoing fill
-- as new confirmed_purchases rows land) means page load is one fast
-- SELECT. yfinance has rate limits and goes flaky; making page render
-- depend on it is the wrong architecture.
--
-- Horizons captured
-- =================
--   t-1  : last close BEFORE filing_date (the baseline)
--   t+0  : close on filing_date (intraday reaction if filing pre-market)
--   t+1  : 1 trading day after filing_date (the canonical "next day" move)
--   t+5  : 5 trading days after (1-week reaction)
--   t+30 : 30 trading days after (1-month reaction)
--
-- Reaction % is computed against t-1 (the baseline) so weekend / holiday
-- filings don't distort the math.

CREATE TABLE IF NOT EXISTS public.backtest_reactions (
  id              BIGSERIAL PRIMARY KEY,

  -- Identity / join-back
  purchase_id     BIGINT,                       -- confirmed_purchases.id (loose ref; not enforced FK)
  ticker          TEXT NOT NULL,
  company         TEXT,
  filing_date     DATE NOT NULL,

  -- Direction classifier output (migration 0013) — enables direction-
  -- stratified stats on the page ("pure buys avg +X%, raise-then-buy
  -- avg -Y%"). Nullable because legacy rows may not have a direction.
  direction       TEXT,
  direction_confidence SMALLINT,

  -- Event size context
  btc_amount      NUMERIC(20, 4),
  usd_amount      NUMERIC(20, 2),

  -- Price snapshots (yfinance close)
  price_t_minus_1 NUMERIC(14, 4),
  price_t_plus_0  NUMERIC(14, 4),
  price_t_plus_1  NUMERIC(14, 4),
  price_t_plus_5  NUMERIC(14, 4),
  price_t_plus_30 NUMERIC(14, 4),

  -- Derived reactions (all vs t-1 baseline, percent)
  reaction_1d_pct  NUMERIC(8, 2),
  reaction_5d_pct  NUMERIC(8, 2),
  reaction_30d_pct NUMERIC(8, 2),

  -- Provenance
  computed_at     TIMESTAMPTZ DEFAULT now() NOT NULL,
  components      JSONB DEFAULT '{}'::jsonb NOT NULL,   -- e.g. {"yfinance_period": "60d", "skipped_reason": "no_baseline"}

  -- One reaction per (ticker, filing_date) — same filing on same day
  -- is the same event; a re-run upserts in place.
  CONSTRAINT backtest_ticker_date_key UNIQUE (ticker, filing_date)
);

-- Most-recent feed (the /backtest page's default sort)
CREATE INDEX IF NOT EXISTS idx_backtest_filing_date
  ON public.backtest_reactions (filing_date DESC);

-- Direction-stratified stats query (group by direction)
CREATE INDEX IF NOT EXISTS idx_backtest_direction
  ON public.backtest_reactions (direction);

-- Per-ticker history (for future per-company drill-down on /mnav/[ticker])
CREATE INDEX IF NOT EXISTS idx_backtest_ticker
  ON public.backtest_reactions (ticker, filing_date DESC);
