-- 0026_divergence_open_alert_unique.sql
--
-- Prevent duplicate OPEN divergence alerts per ticker under concurrency.
--
-- _create_divergence_alert() does SELECT-open-alert -> UPDATE-or-INSERT. Two
-- concurrent reconciles of the same ticker (treasury_sync.reconcile_all racing
-- a per-ticker reconcile_ticker) can both find no open alert and both INSERT,
-- leaving two 'open' rows for one ticker. This partial unique index makes the
-- 2nd insert raise a unique violation instead — the reconciler already catches
-- + logs the insert error, so it degrades to "one open alert per ticker", which
-- is the intended invariant.
--
-- Verified 2026-06-06: 0 tickers currently have >1 open alert, so the index
-- builds cleanly. If that ever changes, dedupe first:
--   UPDATE btc_holdings_divergence_alerts a SET status='superseded'
--    WHERE status='open' AND id < (SELECT max(id) FROM btc_holdings_divergence_alerts b
--                                   WHERE b.ticker=a.ticker AND b.status='open');
--
-- Apply manually in the Supabase SQL editor (DATABASE_URL unset, same as 0022-0025).

CREATE UNIQUE INDEX IF NOT EXISTS uniq_divergence_open_alert_per_ticker
    ON btc_holdings_divergence_alerts (ticker)
    WHERE status = 'open';
