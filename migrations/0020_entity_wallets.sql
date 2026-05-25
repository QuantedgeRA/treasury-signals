-- 0020_entity_wallets.sql
--
-- Wallet-to-entity attribution with confidence scores + source citations.
-- See [[wallet_attribution_design]] for the full design + methodology.
--
-- POSITIONING
-- ===========
-- The strategic review at 2026-05-21 (recovered in
-- [[strategic_review_2026_05_21]]) flagged that Arkham's binary
-- attribution (e.g. their disputed $54.5B MSTR claim) is over-claiming.
-- The product positioning is "more honest" via mandatory:
--   1. confidence_score on every row (0-100, never 100 without
--      primary-source citation)
--   2. attribution_method explicit on every row
--   3. source_citation URL on every row at confidence >= 90
--   4. last_verified date — confidence decays implicitly with age
--
-- This makes wallet attribution AUDITABLE in a way nobody else does.
--
-- INVARIANTS (enforced by application code, not by DB constraint —
-- because confidence_score is a smallint and we want the policy to
-- live in code where it's testable + versioned):
--   - confidence_score > 95 REQUIRES source_citation IS NOT NULL
--   - attribution_method must be one of the documented values
--   - is_active=false signals a wallet that has been emptied or
--     reassigned (kept for historical audit, hidden from default queries)
--
-- IDEMPOTENT — safe to re-run.

CREATE TABLE IF NOT EXISTS public.entity_wallets (
  id                  BIGSERIAL PRIMARY KEY,

  -- Entity identity (links to treasury_companies.ticker)
  ticker              TEXT NOT NULL,
  entity_name         TEXT,                  -- denormalized for query convenience

  -- Wallet identity
  wallet_address      TEXT NOT NULL,
  blockchain          TEXT NOT NULL DEFAULT 'bitcoin',

  -- The honesty mechanics
  confidence_score    SMALLINT NOT NULL,     -- 0-100 (see methodology in design doc)
  attribution_method  TEXT NOT NULL,         -- 'public_disclosure' | 'sec_filing'
                                             -- | 'company_irpage' | 'gov_published'
                                             -- | 'press_release' | 'bitcoin_treasuries'
                                             -- | 'cluster_expansion' (Tier 2)
                                             -- | 'change_addr' (Tier 2)
  source_citation     TEXT,                  -- URL of the 8-K / IR page / govt source

  -- Verification + lifecycle
  first_seen          DATE,
  last_verified       DATE NOT NULL DEFAULT CURRENT_DATE,
  is_active           BOOLEAN NOT NULL DEFAULT true,

  -- On-chain context (refreshed periodically by sanity-check script)
  observed_balance    NUMERIC(20, 4),        -- BTC balance at last_verified
  balance_checked_at  TIMESTAMPTZ,

  -- Audit
  notes               TEXT,
  components          JSONB DEFAULT '{}'::jsonb NOT NULL,
  created_at          TIMESTAMPTZ DEFAULT now() NOT NULL,
  updated_at          TIMESTAMPTZ DEFAULT now() NOT NULL,

  -- One row per (wallet_address) — same wallet can't be claimed by two
  -- entities. If we detect conflict (rare), the lower-confidence claim
  -- gets deactivated.
  CONSTRAINT entity_wallet_address_unique UNIQUE (wallet_address)
);

-- Hot path: "what wallets does X own?" (the /mnav/[ticker] panel + API)
CREATE INDEX IF NOT EXISTS idx_entity_wallets_ticker_active
  ON public.entity_wallets (ticker, is_active, confidence_score DESC);

-- Reverse lookup: "who owns wallet Y?"
-- Address column already has a UNIQUE constraint giving us a btree index.

-- Method-by-confidence query for admin dashboards
CREATE INDEX IF NOT EXISTS idx_entity_wallets_method_conf
  ON public.entity_wallets (attribution_method, confidence_score DESC);

-- Auto-update updated_at
CREATE OR REPLACE FUNCTION public._entity_wallets_touch_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS entity_wallets_touch_updated_at ON public.entity_wallets;
CREATE TRIGGER entity_wallets_touch_updated_at
  BEFORE UPDATE ON public.entity_wallets
  FOR EACH ROW
  EXECUTE FUNCTION public._entity_wallets_touch_updated_at();
