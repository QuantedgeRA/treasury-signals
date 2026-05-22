-- 0015_atm_filings.sql
--
-- ATM (at-the-market) equity-offering filing detection.
--
-- An ATM is a continuous equity offering where a company drip-sells shares
-- into the market via a sales agent. For BTC treasury companies, ATM
-- proceeds typically fund the next BTC purchase — so the filing IS the
-- leading indicator. Strategy's $21B "21/21" ATM is the canonical example:
-- every announced BTC buy in 2024-2025 was funded out of the ATM.
--
-- BitcoinQuant tracks Strategy's ATM via STRC volume; this table generalizes
-- to every public treasury company by parsing the underlying SEC forms:
--
--   S-3 / S-3/A  — shelf registration; declares max raise capacity
--   424B5        — prospectus supplement filed when a shelf takedown happens
--                  (the actual issuance event)
--   424B7        — registration-statement supplements (sometimes ATM-related)
--
-- We persist the most-recent state per (ticker, accession_number). The
-- table is keyed on accession_number so re-scans are idempotent.
--
-- status column values:
--   'shelf'     — S-3 registered, no takedown yet (capacity only)
--   'active'    — sales agreement / ATM in place, actively selling
--   'takedown'  — 424B prospectus supplement filed (= an issuance event)
--
-- This is a thin ledger. The analytical work — joining ATM filings to
-- volume spikes to predict BTC purchases — happens in the equity-volume
-- tracker (Tier-2 build #2 follow-up).

CREATE TABLE IF NOT EXISTS public.atm_filings (
  id                BIGSERIAL PRIMARY KEY,

  -- Identity
  ticker            TEXT NOT NULL,
  company           TEXT,
  cik               TEXT,

  -- Filing metadata
  accession_number  TEXT NOT NULL,
  form_type         TEXT NOT NULL,                -- 'S-3', 'S-3/A', '424B5', '424B7'
  filing_date       DATE NOT NULL,
  filing_url        TEXT,

  -- Parsed economics
  status            TEXT NOT NULL DEFAULT 'shelf', -- shelf | active | takedown
  max_capacity_usd  NUMERIC(20, 2),                -- "up to $X" from S-3 cover
  sales_agent       TEXT,                          -- e.g. 'Cantor Fitzgerald', 'TD Cowen'

  -- Provenance
  excerpt           TEXT,                          -- 500-char chunk around the match
  components        JSONB DEFAULT '{}'::jsonb NOT NULL,
  created_at        TIMESTAMPTZ DEFAULT now() NOT NULL,

  CONSTRAINT atm_filings_accession_key UNIQUE (accession_number)
);

-- Hot path: latest filings per ticker (dashboard ATM panel + equity-vol cross-ref)
CREATE INDEX IF NOT EXISTS idx_atm_filings_ticker_date
  ON public.atm_filings (ticker, filing_date DESC);

-- Active-ATM lookup: "which companies have a live shelf right now?"
CREATE INDEX IF NOT EXISTS idx_atm_filings_status_date
  ON public.atm_filings (status, filing_date DESC);
