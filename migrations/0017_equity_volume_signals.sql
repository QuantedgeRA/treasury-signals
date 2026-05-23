-- 0017_equity_volume_signals.sql
--
-- Persist the output of scanners/equity_volume_tracker.py so the customer
-- dashboard has data to read.
--
-- Today the tracker only emits Telegram alerts and logs to console. To
-- surface signals on /signals (the new web-app page), we need a queryable
-- ledger. One row per (ticker, signal_date) — the tracker runs once daily
-- from the morning scan, so daily granularity is correct.
--
-- This table is read by:
--   • /signals page (paid-tier feature, customer-facing)
--   • Future: per-subscriber watchlist filter for equity-volume signals
--
-- Trust note: equity-volume signals are CORRELATION leading indicators
-- (volume spike + active ATM = likely BTC buy), not confirmed events.
-- They live in their own table — NOT in confirmed_purchases. The 8-K
-- detection pipeline writes the actual confirmed purchase.

CREATE TABLE IF NOT EXISTS public.equity_volume_signals (
  id                BIGSERIAL PRIMARY KEY,

  -- Identity
  ticker            TEXT NOT NULL,
  company           TEXT,

  -- Snapshot
  signal_date       DATE NOT NULL,

  -- Classification (matches EquityVolumeSignal.level in the tracker)
  level             TEXT NOT NULL,    -- VERY_HIGH | HIGH | ELEVATED | SUPPRESSED | NORMAL
  is_signal         BOOLEAN NOT NULL DEFAULT false,

  -- Volume math
  volume_ratio          NUMERIC(8, 2),
  volume                BIGINT,
  avg_volume            BIGINT,
  dollar_volume_m       NUMERIC(12, 2),    -- today's dollar volume in millions
  avg_dollar_volume_m   NUMERIC(12, 2),
  price                 NUMERIC(14, 4),

  -- ATM context (joined from atm_filings)
  has_active_atm    BOOLEAN NOT NULL DEFAULT false,
  atm_capacity_usd  NUMERIC(20, 2),
  atm_status        TEXT,

  -- Narrative
  message           TEXT,
  components        JSONB DEFAULT '{}'::jsonb NOT NULL,
  created_at        TIMESTAMPTZ DEFAULT now() NOT NULL,

  -- One row per ticker per day (re-runs same day overwrite)
  CONSTRAINT eq_vol_signal_ticker_date_key UNIQUE (ticker, signal_date)
);

-- Hot path: most recent signals across all tickers, filtered by level
CREATE INDEX IF NOT EXISTS idx_eq_vol_date_level
  ON public.equity_volume_signals (signal_date DESC, level);

-- Per-ticker history (the future ticker drill-down page)
CREATE INDEX IF NOT EXISTS idx_eq_vol_ticker_date
  ON public.equity_volume_signals (ticker, signal_date DESC);

-- Live signals feed (is_signal=true filter for the customer alerts feed)
CREATE INDEX IF NOT EXISTS idx_eq_vol_signal_only
  ON public.equity_volume_signals (signal_date DESC, level)
  WHERE is_signal = true;
