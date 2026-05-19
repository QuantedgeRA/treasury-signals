-- 0014_mnav_history.sql
--
-- mNAV (market-to-NAV) history table.
--
-- mNAV = market_cap / (btc_holdings × btc_price)
--
-- Where market_cap = shares_outstanding × stock_price. Reading from the
-- right is a treasury company's mNAV says how much premium (mNAV > 1) or
-- discount (mNAV < 1) the equity is trading at relative to its BTC stack.
--
-- MSTR has historically traded at 1.5-3x mNAV; premium compression is a
-- leading equity-weakness indicator that doesn't show up in BTC price.
-- BitcoinQuant monetizes this signal for MSTR alone; this table is the
-- substrate for extending the playbook to the other ~200 treasury cos —
-- the Tier-2 hedge-fund-analyst tier opportunity.
--
-- One row per (ticker, snapshot_date). Snapshot date is the actual stock
-- close date (not the cron run time) so weekend / holiday gaps are
-- visible.
--
-- Sources: stock_price from yfinance (close at snapshot_date), btc_price
-- from leaderboard_snapshots same day, shares_outstanding & btc_holdings
-- from treasury_companies (latest sync). Any computation that hits
-- division-by-zero or missing input is skipped, not zero-filled.

CREATE TABLE IF NOT EXISTS public.mnav_history (
  id              BIGSERIAL PRIMARY KEY,

  -- Identity
  ticker          TEXT NOT NULL,
  company         TEXT,

  -- Snapshot
  snapshot_date   DATE NOT NULL,

  -- Core inputs (denormalized so a row is self-contained for audit)
  shares_outstanding   BIGINT,
  stock_price          NUMERIC(14, 4),
  btc_holdings         BIGINT,
  btc_price            NUMERIC(14, 2),

  -- Derived
  market_cap      NUMERIC(20, 2),   -- shares_outstanding × stock_price
  btc_value       NUMERIC(20, 2),   -- btc_holdings × btc_price
  mnav            NUMERIC(8, 4),    -- market_cap / btc_value

  -- Provenance
  components      JSONB DEFAULT '{}'::jsonb NOT NULL,   -- {"stock_source": "yfinance", "btc_source": "leaderboard_snapshots"}
  created_at      TIMESTAMPTZ DEFAULT now() NOT NULL,

  -- One row per ticker per day
  CONSTRAINT mnav_history_ticker_date_key UNIQUE (ticker, snapshot_date)
);

-- Hot path: latest snapshot per ticker (for the /mnav dashboard page)
CREATE INDEX IF NOT EXISTS idx_mnav_ticker_date
  ON public.mnav_history (ticker, snapshot_date DESC);

-- Ranked feed: highest premium / largest discount today
CREATE INDEX IF NOT EXISTS idx_mnav_date_value
  ON public.mnav_history (snapshot_date DESC, mnav DESC);
