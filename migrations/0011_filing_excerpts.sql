-- 0011_filing_excerpts.sql
--
-- BTC-relevant filing excerpts — the workflow-lock-in moat.
--
-- Background: edgar_realtime + global_filing_scanner already detect new
-- 8-K filings and store an aggregate row in edgar_filings (one row per
-- filing, with regex-extracted btc_amount + event_type). That's enough
-- for the leaderboard / purchases pipeline.
--
-- It is NOT enough for a treasury operator who needs to read the actual
-- language a peer used in their filing — the sentence that names a new
-- BTC reserve policy, the disclosure that says "we suspended purchases
-- pending board review", the risk factor about custody arrangements.
-- That sentence is the unit a CFO or IR lead actually wants in their
-- inbox within 10 minutes of the filing landing on EDGAR.
--
-- This table stores those sentences. One filing produces 1-N excerpt
-- rows (one per BTC-relevant sentence Claude flags as material).
--
-- ── Why a separate table, not a JSONB column on edgar_filings ──────────
-- Three reasons:
--   1. We want to query "give me the last 50 high-impact excerpts across
--      all companies" without unpacking JSON. A flat row layout indexed
--      on (impact_score, created_at) is the hot path for the /filings
--      feed view and the daily digest.
--   2. Slack/email delivery state (alerted_at) lives per-excerpt, not
--      per-filing. A single 10-Q might have 4 excerpts where 2 are
--      high-impact (auto-alert) and 2 are lower-impact (digest only).
--   3. We may re-score excerpts as the Claude prompt evolves. Easier to
--      upsert rows than to mutate a JSONB array.
--
-- ── Categories ─────────────────────────────────────────────────────────
-- Claude classifies each excerpt into one of:
--   acquisition       — new BTC purchase, holdings increased
--   sale              — BTC sold, divested, liquidated
--   financing         — capital raise tied to BTC strategy (convertible
--                       notes, ATM offerings, ATM proceeds earmarked for BTC)
--   policy_change     — treasury policy update, new reserve target,
--                       board mandate, custody arrangement change
--   risk_factor       — disclosure language about BTC volatility,
--                       custody risk, regulatory risk
--   forward_looking   — guidance, targets, intentions ("plans to",
--                       "expects to acquire") — NOT confirmed purchases
--   general           — mentions BTC but doesn't fit the categories
--
-- The category drives both the UI badge and the alert rule (acquisition
-- + sale + financing always alert ≥ 60; risk_factor alerts at ≥ 80;
-- forward_looking digest-only).
--
-- ── alerted_at semantics ───────────────────────────────────────────────
-- NULL means "not yet pushed to any delivery channel". Once the Slack
-- (or email) sender picks up this excerpt and posts, set alerted_at.
-- Idempotency: the sender's WHERE clause is "alerted_at IS NULL AND
-- impact_score >= threshold" so a missed scheduler tick never
-- double-posts.

CREATE TABLE IF NOT EXISTS public.filing_excerpts (
  id              BIGSERIAL PRIMARY KEY,
  -- edgar_filings.id is SERIAL (INT), so FK type matches as INTEGER.
  filing_id       INTEGER REFERENCES public.edgar_filings(id) ON DELETE CASCADE,

  -- Denormalized fields — kept here so the /filings feed and Slack sender
  -- never need to join edgar_filings. Worth the disk cost.
  accession_number TEXT,
  company_name    TEXT,
  ticker          TEXT,
  filing_date     DATE,
  filing_url      TEXT,
  form_type       TEXT,

  -- The actual extracted content
  excerpt_text    TEXT NOT NULL,
  claude_summary  TEXT,
  impact_score    SMALLINT NOT NULL CHECK (impact_score BETWEEN 0 AND 100),
  category        TEXT NOT NULL CHECK (category IN (
    'acquisition', 'sale', 'financing', 'policy_change',
    'risk_factor', 'forward_looking', 'general'
  )),
  btc_amount      NUMERIC,
  usd_amount      NUMERIC,

  -- Lifecycle timestamps
  extracted_at    TIMESTAMPTZ DEFAULT now() NOT NULL,
  alerted_at      TIMESTAMPTZ,
  created_at      TIMESTAMPTZ DEFAULT now() NOT NULL
);

-- Feed view hot path: "top 50 high-impact excerpts, newest first"
CREATE INDEX IF NOT EXISTS idx_filing_excerpts_impact_recency
  ON public.filing_excerpts (impact_score DESC, created_at DESC);

-- Company timeline: "everything tracked for this ticker, newest first"
CREATE INDEX IF NOT EXISTS idx_filing_excerpts_ticker_date
  ON public.filing_excerpts (ticker, filing_date DESC)
  WHERE ticker IS NOT NULL AND ticker <> '';

-- Delivery queue: "all excerpts not yet alerted, ordered for FIFO push"
-- Partial index — the table will be mostly alerted excerpts long-term,
-- so the unindexed-alerted bulk doesn't bloat this.
CREATE INDEX IF NOT EXISTS idx_filing_excerpts_pending_alert
  ON public.filing_excerpts (created_at)
  WHERE alerted_at IS NULL;

-- Per-filing lookup (for the /filings/[accession] detail page later)
CREATE INDEX IF NOT EXISTS idx_filing_excerpts_filing
  ON public.filing_excerpts (filing_id);

-- Category filter for the feed UI
CREATE INDEX IF NOT EXISTS idx_filing_excerpts_category
  ON public.filing_excerpts (category, created_at DESC);
