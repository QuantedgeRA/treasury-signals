-- 0022_purchase_dedup_constraints.sql
--
-- HARD database-level guarantee that the same purchase/sale event can never
-- be stored twice in confirmed_purchases / confirmed_sales — regardless of
-- which code path writes it.
--
-- WHY
-- ===
-- confirmed_purchases / confirmed_sales had ~17 writers (the bitbo scraper,
-- every backfill_entities*.py, scripts/backfill_strategy.py, etc.) writing
-- DIRECTLY to the tables, bypassing purchase_reconciler.reconcile_and_save().
-- Each writer minted its own purchase_id scheme:
--     reconciler : confirmed_{norm_ticker}_{date}
--     scraper    : scraped_{ticker}_{date}_{int(btc)}
--     backfills  : backfill_{ticker}_{date}_{int(btc)}
-- so the SAME event got different primary keys and coexisted as duplicates.
-- The 2026-06-01 audit found exactly that: MSTR 4,871 BTC on 2026-04-06 stored
-- once via EDGAR and once via a bitbo backfill, plus a BMNR / BMNR.US twin.
-- Those 2 rows were cleaned manually; this migration stops it recurring.
--
-- This is the purchases-table analogue of the 2026-05-22 btc_holdings
-- single-writer fix ([[btc_holdings_reconciler_architecture]]).
--
-- THE NATURAL KEY
-- ===============
-- (normalize_ticker(ticker), filing_date, btc_amount)
--
-- btc_amount is part of the key ON PURPOSE. Companies legitimately make
-- MULTIPLE distinct purchases on the SAME day — e.g. El Salvador's
-- "second buy same day, buying the dip" (SV.GOV 2021-09-07: 400 + 150 BTC),
-- or MARA's split Dec-2024 tranches (6,560 + 5,214). Those differ by amount,
-- so they remain DISTINCT rows. A true duplicate is the same event copied by
-- two sources — same ticker, same date, same amount — and that is what the
-- unique index forbids. btc_amount is numeric, so 4871 and 4871.0 collide
-- correctly. Verified 0 collisions on both tables before adding the index.
--
-- normalize_ticker() MUST stay in lockstep with
-- purchase_reconciler._normalize_ticker_for_dedup() and
-- treasury_signals/pipelines/purchase_keys.normalize_ticker(). The suffix
-- list below is copied from there verbatim — note it intentionally does NOT
-- include ".T" (Japanese tickers like 3825.T keep their suffix).
--
-- IDEMPOTENT — safe to re-run.

-- ── Canonical ticker normalizer (IMMUTABLE so it can index) ──────────────
CREATE OR REPLACE FUNCTION public.dedup_normalize_ticker(t text)
RETURNS text
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT regexp_replace(
    upper(btrim(coalesce(t, ''))),
    '\.(US|L|TO|AX|DE|PA|SW|HK|KS|SS|SZ|SA|V|ST|CO|MI|BR|MC|OL|HE|IS)$',
    ''
  )
$$;

-- ── One row per (normalized ticker, filing_date, btc_amount) ─────────────
-- If either of these fails to create, a duplicate slipped in after the
-- pre-check — run scripts/audit_purchase_dupes.py, clean it, and re-run.
CREATE UNIQUE INDEX IF NOT EXISTS ux_confirmed_purchases_natural
  ON public.confirmed_purchases (
    public.dedup_normalize_ticker(ticker),
    filing_date,
    btc_amount
  );

CREATE UNIQUE INDEX IF NOT EXISTS ux_confirmed_sales_natural
  ON public.confirmed_sales (
    public.dedup_normalize_ticker(ticker),
    filing_date,
    btc_amount
  );
