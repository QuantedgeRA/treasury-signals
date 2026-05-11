-- 0012_pre_announcement_signals.sql
--
-- Pre-announcement signal persistence — Week 5 of the persona-A roadmap
-- (memory/product_strategy_2026_05.md). Stores periodic snapshots of the
-- in-memory CorrelationEngineV2 state so the frontend, Slack dispatcher,
-- and downstream consumers can read "which companies look like they're
-- about to file" without re-running the engine themselves.
--
-- Background: the existing CorrelationEngineV2 lives in
-- treasury_signals/scheduler/__init__.py as a process-singleton. It
-- accumulates signals from 6 streams (tweets, STRC, EDGAR, global
-- filings, whale on-chain, news) plus a 7th added in this slice
-- (filing_excerpts from the Week 2-3 build). On every scheduler tick,
-- engine.calculate_correlation() produces a ranked list of companies
-- with composite scores 0-100. That ranking was previously surfaced
-- only in Telegram alerts and email briefings — never persisted for
-- the dashboard.
--
-- This migration adds the storage layer.
--
-- ── Per-company row, not per-signal ────────────────────────────────────
-- Each row represents ONE company's composite state at ONE snapshot
-- time. The component signals (which streams fired, which excerpts,
-- which tweets) live inside the `components` JSONB field. We don't
-- normalize them — that would couple the schema to the engine's
-- internal stream taxonomy, which has churned twice already.
--
-- ── alerted_at, threshold_at semantics ─────────────────────────────────
-- alerted_at: set when the Slack dispatcher posts this signal to teams.
--             Used to dedup so we don't re-alert on the same company
--             every scheduler tick.
-- threshold_at: set the first time a company's score crossed 60 (HIGH).
--               Used to compute "lead time" once a confirmed purchase
--               eventually lands — measures how early we caught it.
--               Stays set across subsequent snapshots; never reset.
--
-- ── Rolling retention ──────────────────────────────────────────────────
-- The correlation window is 48h, so signals older than that decay out
-- of the engine. We mirror that on the DB side: anything older than
-- 72h can be safely deleted by a cleanup job. The partial index on
-- (snapshot_at) + the row size make this cheap.

CREATE TABLE IF NOT EXISTS public.pre_announcement_signals (
  id              BIGSERIAL PRIMARY KEY,

  -- Identity
  ticker          TEXT NOT NULL,
  company         TEXT,

  -- Composite score
  score           SMALLINT NOT NULL CHECK (score BETWEEN 0 AND 100),
  raw_score       SMALLINT,        -- pre-multiplier sum of component scores
  num_streams     SMALLINT,        -- how many distinct streams fired
  multiplier      REAL,            -- multi-stream multiplier applied

  -- Components — JSON blob mirroring engine output for the dashboard
  -- Shape: {"streams": ["tweet","edgar","filing_excerpt"],
  --         "reasons": ["tweet: @saylor — 'orange pill'", ...],
  --         "top_excerpt_id": 42,   -- optional FK to filing_excerpts
  --         "top_filing_url": "...",
  --         "fear_greed": 31,
  --         "btc_weekly_change": -8.3}
  components      JSONB DEFAULT '{}'::jsonb NOT NULL,

  -- Market context at snapshot time (denormalized for fast feed reads)
  market_score    SMALLINT,
  alert_level     TEXT,            -- NONE / LOW / MEDIUM / HIGH / CRITICAL

  -- Lifecycle
  snapshot_at     TIMESTAMPTZ DEFAULT now() NOT NULL,
  alerted_at      TIMESTAMPTZ,
  threshold_at    TIMESTAMPTZ,     -- first time score >= 60

  created_at      TIMESTAMPTZ DEFAULT now() NOT NULL
);

-- Hot path: "latest snapshot per ticker, top N by score" for the feed
CREATE INDEX IF NOT EXISTS idx_pre_announce_score_recency
  ON public.pre_announcement_signals (score DESC, snapshot_at DESC);

-- Latest per-ticker lookup (used by feed UI to dedup snapshots)
CREATE INDEX IF NOT EXISTS idx_pre_announce_ticker_recency
  ON public.pre_announcement_signals (ticker, snapshot_at DESC);

-- Delivery queue: pending Slack pushes
CREATE INDEX IF NOT EXISTS idx_pre_announce_pending_alert
  ON public.pre_announcement_signals (snapshot_at DESC)
  WHERE alerted_at IS NULL AND score >= 60;

-- Retention cleanup query support
CREATE INDEX IF NOT EXISTS idx_pre_announce_snapshot_at
  ON public.pre_announcement_signals (snapshot_at);
