-- 0021_wallet_clusters_and_movements.sql
--
-- Tier 2 + Tier 3 substrate for [[wallet_attribution_design]]:
--   * wallet_clusters    — the lineage of how a heuristic-derived
--                          attribution was reached (seed → hops → derived)
--   * wallet_movements   — the audit trail of every observed transfer
--                          involving a tracked entity wallet
--
-- See entity_wallets (migration 0020) for the canonical attribution
-- table. These two new tables exist to give every Tier 2/3 attribution
-- + alert a verifiable, queryable history. "Show your work" is the
-- positioning vs. Arkham; these tables are the work shown.
--
-- IDEMPOTENT — safe to re-run.

-- ─────────────────────────────────────────────────────────────────────
-- wallet_clusters — derivation lineage for Tier 2 attributions
-- ─────────────────────────────────────────────────────────────────────
-- When the clusterer adds a wallet to entity_wallets via cluster_expansion
-- or change_addr, it also writes a row here documenting:
--   - which seed wallet it came from
--   - hop distance from the seed
--   - which heuristic fired (common_input / change_addr)
--   - the on-chain evidence (tx hashes, input/output indexes)
--
-- This is the audit trail a customer (or auditor) can use to verify
-- "why does TSI think this wallet is MSTR?" One row per
-- (derived_address, seed_address) pair — different seeds reaching the
-- same derived address get separate rows.

CREATE TABLE IF NOT EXISTS public.wallet_clusters (
  id                BIGSERIAL PRIMARY KEY,

  -- Identity
  derived_address   TEXT NOT NULL,
  seed_address      TEXT NOT NULL,
  ticker            TEXT NOT NULL,            -- denormalized for query convenience

  -- Lineage
  hop_distance      SMALLINT NOT NULL,        -- 1 = seed's immediate cluster
  heuristic         TEXT NOT NULL,            -- 'common_input' | 'change_addr'

  -- Confidence assignment
  confidence_score  SMALLINT NOT NULL,        -- 0-100, propagated to entity_wallets
  confidence_decay  SMALLINT NOT NULL DEFAULT 10,  -- penalty applied per hop

  -- Evidence (the "show your work" part)
  evidence_tx_hash  TEXT,                     -- transaction that links seed + derived
  evidence_notes    TEXT,
  components        JSONB DEFAULT '{}'::jsonb NOT NULL,

  -- Audit
  created_at        TIMESTAMPTZ DEFAULT now() NOT NULL,

  CONSTRAINT cluster_seed_derived_unique UNIQUE (derived_address, seed_address)
);

CREATE INDEX IF NOT EXISTS idx_wallet_clusters_derived
  ON public.wallet_clusters (derived_address);
CREATE INDEX IF NOT EXISTS idx_wallet_clusters_seed
  ON public.wallet_clusters (seed_address, hop_distance);
CREATE INDEX IF NOT EXISTS idx_wallet_clusters_ticker
  ON public.wallet_clusters (ticker, hop_distance);


-- ─────────────────────────────────────────────────────────────────────
-- wallet_movements — every observed transfer of a tracked wallet
-- ─────────────────────────────────────────────────────────────────────
-- Populated by pipelines/wallet_monitor.py. Each row = one inflow or
-- outflow observed on a wallet we've attributed to an entity. The
-- monitor classifies destinations + sources where possible so traders
-- can act on "MSTR sent 500 BTC to a Coinbase deposit pattern" with
-- confidence.
--
-- ONE row per (tx_hash, wallet_address, direction). A single transaction
-- moving BTC FROM wallet A TO wallet B (both tracked) writes 2 rows:
-- one outflow from A, one inflow to B. This is the audit-friendly shape.

CREATE TABLE IF NOT EXISTS public.wallet_movements (
  id                BIGSERIAL PRIMARY KEY,

  -- Identity
  tx_hash           TEXT NOT NULL,
  wallet_address    TEXT NOT NULL,            -- the tracked side
  ticker            TEXT NOT NULL,            -- denormalized for the dashboard

  -- Movement
  direction         TEXT NOT NULL,            -- 'inflow' | 'outflow'
  btc_amount        NUMERIC(20, 8) NOT NULL,  -- 8 decimals = satoshis precision
  block_time        TIMESTAMPTZ,
  block_height      BIGINT,

  -- Counterparty (the OTHER side of the transfer — may be unknown)
  counterparty_address    TEXT,
  counterparty_entity     TEXT,                -- ticker of attributed entity, if known
  counterparty_label      TEXT,                -- 'exchange_deposit' | 'cold_storage' |
                                               -- 'unknown' | etc.
  counterparty_confidence SMALLINT,            -- 0-100

  -- Customer-facing classification
  classification     TEXT NOT NULL DEFAULT 'unknown',
  -- one of: 'internal_reorg' (both sides same entity, no signal)
  --       | 'exchange_inflow' (suspected sale)
  --       | 'exchange_outflow' (suspected new purchase / withdrawal)
  --       | 'custody_change' (move to a different custodian)
  --       | 'unknown'
  alert_dispatched   BOOLEAN NOT NULL DEFAULT false,

  -- Audit
  discovered_at     TIMESTAMPTZ DEFAULT now() NOT NULL,
  components        JSONB DEFAULT '{}'::jsonb NOT NULL,

  -- Same tx + wallet + direction is idempotent
  CONSTRAINT movement_tx_wallet_dir_unique
    UNIQUE (tx_hash, wallet_address, direction)
);

-- Hot path: customer dashboard "what moved on MSTR's wallets last 7 days"
CREATE INDEX IF NOT EXISTS idx_movements_ticker_time
  ON public.wallet_movements (ticker, block_time DESC);

-- Per-wallet lookup
CREATE INDEX IF NOT EXISTS idx_movements_wallet_time
  ON public.wallet_movements (wallet_address, block_time DESC);

-- Alert queue: unalerted exchange_inflow events are the sell signals
CREATE INDEX IF NOT EXISTS idx_movements_alert_queue
  ON public.wallet_movements (classification, alert_dispatched, block_time DESC)
  WHERE classification IN ('exchange_inflow', 'exchange_outflow', 'custody_change');
