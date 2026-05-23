-- 0016_btc_holdings_observations.sql
--
-- Divergence-proof source-of-truth architecture for treasury_companies.btc_holdings.
--
-- BACKGROUND (root cause for migration, 2026-05-22)
-- =================================================
-- treasury_companies.btc_holdings was being written directly by ~25 different
-- modules with no coordinated arbitration ("whoever writes last wins"). The
-- KEEL bug surfaced this: CoinGecko's stale 1,558 BTC value was overwriting
-- BitcoinTreasuries.net's correct 2,469 because CoinGecko was configured as
-- the Layer 1 PRIMARY in treasury_sync.py. The pre-existing `data_source`
-- column was intended to be a trust hierarchy but collapsed to a single
-- value ('aggregator') across 339 of 340 rows.
--
-- This migration introduces the substrate for a permanent fix:
--
--   1. btc_holdings_observations  — append-only ledger, one row per
--      (ticker, source, observation_time). Every data source writes here
--      with its raw claim. No single source can clobber another's value.
--
--   2. btc_holdings_divergence_alerts — when sources disagree by more than
--      a threshold, a row is written here for human review + Telegram alert.
--
--   3. treasury_companies extra columns — `btc_resolved_source` /
--      `btc_resolved_at` / `btc_divergence_spread_pct` / `btc_divergence_alert_id`
--      track WHICH source's value won the resolution and when, so every
--      btc_holdings number on screen is auditable to a citation.
--
-- ARCHITECTURE (post-migration)
-- =============================
-- Sources (CoinGecko, BitcoinTreasuries, EDGAR, press releases, manual)
--   ──> record_observation(ticker, source, value, ...)
--           ──> btc_holdings_observations.INSERT
--
-- pipelines/btc_holdings_reconciler.py
--   ──> reads recent observations per ticker
--   ──> applies trust hierarchy + staleness penalty
--   ──> writes btc_holdings + provenance to treasury_companies
--   ──> writes divergence_alerts when spread > threshold
--
-- The reconciler becomes the ONLY writer of treasury_companies.btc_holdings.
-- Every other writer is migrated to record_observation() instead.
--
-- IDEMPOTENCY
-- ===========
-- All CREATE statements use IF NOT EXISTS. ADD COLUMN clauses use
-- IF NOT EXISTS. Safe to re-run.

-- ─────────────────────────────────────────────────────────────────────────
-- 1. Observations ledger
-- ─────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.btc_holdings_observations (
  id              BIGSERIAL PRIMARY KEY,

  -- Identity
  ticker          TEXT NOT NULL,
  source          TEXT NOT NULL,         -- 'coingecko' | 'bitcointreasuries' | 'edgar_8k' | 'manual_override' | etc.

  -- Claim
  btc_value       NUMERIC(20, 4) NOT NULL,
  observed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  source_timestamp TIMESTAMPTZ,           -- when source itself was last updated (if known)

  -- Audit trail
  source_url      TEXT,
  excerpt         TEXT,
  components      JSONB DEFAULT '{}'::jsonb NOT NULL,
  created_at      TIMESTAMPTZ DEFAULT now() NOT NULL
);

-- Hot path: latest observation per (ticker, source)
CREATE INDEX IF NOT EXISTS idx_btc_obs_ticker_source_date
  ON public.btc_holdings_observations (ticker, source, observed_at DESC);

-- Ranked feed: most recently observed across all sources, for the
-- reconciler's "what changed today" query.
CREATE INDEX IF NOT EXISTS idx_btc_obs_observed_at_desc
  ON public.btc_holdings_observations (observed_at DESC);


-- ─────────────────────────────────────────────────────────────────────────
-- 2. Divergence alerts
-- ─────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.btc_holdings_divergence_alerts (
  id              BIGSERIAL PRIMARY KEY,

  -- Identity
  ticker          TEXT NOT NULL,
  detected_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

  -- Snapshot of conflicting claims at detection time. Shape:
  --   { "coingecko": {"value": 1558, "observed_at": "2026-05-22T..."},
  --     "bitcointreasuries": {"value": 2469, "observed_at": "2026-05-22T..."} }
  source_values   JSONB NOT NULL,

  -- Statistics
  min_value       NUMERIC(20, 4),
  max_value       NUMERIC(20, 4),
  spread_btc      NUMERIC(20, 4),         -- max - min
  spread_pct      NUMERIC(8, 2),          -- (max - min) / max × 100

  -- Resolution decision
  resolved_value  NUMERIC(20, 4),
  resolved_source TEXT,
  resolved_trust_score NUMERIC(6, 2),

  -- Workflow
  status          TEXT NOT NULL DEFAULT 'open',  -- open | acknowledged | resolved
  human_note      TEXT,
  acknowledged_by TEXT,                    -- email of admin who triaged
  acknowledged_at TIMESTAMPTZ
);

-- Hot path: open alerts (the human-attention queue)
CREATE INDEX IF NOT EXISTS idx_divergence_open_date
  ON public.btc_holdings_divergence_alerts (status, detected_at DESC);

-- Per-ticker history (how often does X diverge?)
CREATE INDEX IF NOT EXISTS idx_divergence_ticker_date
  ON public.btc_holdings_divergence_alerts (ticker, detected_at DESC);


-- ─────────────────────────────────────────────────────────────────────────
-- 3. Provenance columns on treasury_companies
-- ─────────────────────────────────────────────────────────────────────────
-- Every btc_holdings value should be traceable to a source + timestamp.
-- These columns are populated by the reconciler whenever it writes a new
-- value. A row with NULL provenance was written by the legacy code path
-- and will be backfilled on first reconcile.

ALTER TABLE public.treasury_companies
  ADD COLUMN IF NOT EXISTS btc_resolved_source TEXT,
  ADD COLUMN IF NOT EXISTS btc_resolved_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS btc_divergence_spread_pct NUMERIC(8, 2),
  ADD COLUMN IF NOT EXISTS btc_divergence_alert_id BIGINT;

-- Cross-reference index for the divergence-alerts admin page
CREATE INDEX IF NOT EXISTS idx_treasury_companies_resolved_source
  ON public.treasury_companies (btc_resolved_source);


-- ─────────────────────────────────────────────────────────────────────────
-- 4. View for the admin divergence dashboard (optional but cheap)
-- ─────────────────────────────────────────────────────────────────────────
-- One-row-per-ticker view that joins current treasury_companies state
-- with its most-recent observations per source. Makes the "why is X's
-- value Y?" question a one-line SELECT.

CREATE OR REPLACE VIEW public.v_btc_holdings_provenance AS
SELECT
  tc.ticker,
  tc.company,
  tc.btc_holdings,
  tc.btc_resolved_source,
  tc.btc_resolved_at,
  tc.btc_divergence_spread_pct,
  tc.btc_divergence_alert_id,
  tc.last_updated AS treasury_last_updated,
  obs.observations
FROM public.treasury_companies tc
LEFT JOIN LATERAL (
  SELECT jsonb_object_agg(latest.source,
                          jsonb_build_object(
                            'value', latest.btc_value,
                            'observed_at', latest.observed_at,
                            'source_url', latest.source_url
                          )) AS observations
  FROM (
    SELECT DISTINCT ON (source)
      source, btc_value, observed_at, source_url
    FROM public.btc_holdings_observations
    WHERE ticker = tc.ticker
    ORDER BY source, observed_at DESC
  ) latest
) obs ON true;
