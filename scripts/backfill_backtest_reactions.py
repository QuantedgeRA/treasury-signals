"""
One-shot + cron-able: compute equity reactions around every
confirmed_purchase event and persist into backtest_reactions
(migration 0019).

Powers the public /backtest landing-page asset.

Inputs:
  confirmed_purchases (ticker, filing_date, btc_amount, usd_amount,
                       direction, direction_confidence)
  yfinance daily-close history per ticker

Outputs:
  backtest_reactions row per (ticker, filing_date), idempotent upsert.

Horizons:
  t-1   : last close BEFORE filing_date (skip weekends/holidays)
  t+0   : close on filing_date (if open)
  t+1   : 1 trading day after filing_date
  t+5   : 5 trading days after
  t+30  : 30 trading days after

Reactions all expressed as % vs t-1 baseline. A negative reaction is a
real signal (GameStop -22.5% on dilutive raise — exactly the kind of
event the direction classifier exists to flag).

Usage:
    python scripts/backfill_backtest_reactions.py           # dry-run summary
    python scripts/backfill_backtest_reactions.py --apply   # actually write

Idempotent: re-running upserts in place. Future runs will pick up new
confirmed_purchases since last execution. Designed to be called from the
scheduler (post_scan.run_heavy_maintenance) after the morning sync —
that way new purchases get backtested within 24 hours of detection.
"""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

# Allow `from treasury_signals.*` imports when invoked as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
if not (SUPABASE_URL and SUPABASE_KEY):
    sys.exit("SUPABASE_URL + SUPABASE_KEY required in .env")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
apply = "--apply" in sys.argv

# Caps so a single run can never balloon. yfinance is rate-limited and
# slow; this script is the heavy one in the morning scan window.
MAX_PURCHASES_PER_RUN = 500
# Two years of daily data covers every confirmed_purchases.filing_date we
# care about (we filter to last 730 days). yfinance "2y" is faster than
# "max" and gives consistent coverage. Bumped from "90d" 2026-05-23 after
# realizing the 90d window only contains t-1 close for the most recent
# ~3 months of events.
YFINANCE_PERIOD = "2y"


print(f"Mode: {'APPLYING' if apply else 'DRY-RUN (pass --apply to write)'}")
print("=" * 70)


def _fetch_uncomputed_purchases(limit: int) -> list[dict]:
    """confirmed_purchases rows that lack a backtest_reactions row.

    Returns earliest-first so older events get backfilled first. New
    events near the filing_date may not have t+30 data yet — those still
    get a row with partial fill (the page handles NULL reactions
    gracefully).
    """
    try:
        # Pull recent confirmed_purchases (we cap by lookback to avoid
        # historical data with no yfinance coverage)
        cutoff = (datetime.utcnow() - timedelta(days=730)).strftime("%Y-%m-%d")
        res = (
            supabase.table("confirmed_purchases")
            .select("id, ticker, company, filing_date, btc_amount, usd_amount, direction, direction_confidence")
            .gte("filing_date", cutoff)
            .order("filing_date", desc=False)
            .limit(limit)
            .execute()
        )
        candidates = [r for r in (res.data or []) if r.get("ticker") and r.get("filing_date")]
    except Exception as e:
        print(f"  ERROR: fetch purchases failed: {e}")
        return []

    # Strip .US suffix on ticker (per [[btc_holdings_reconciler_architecture]]
    # the canonical form is bare). yfinance also wants bare.
    for c in candidates:
        t = (c.get("ticker") or "").strip().upper()
        if t.endswith(".US") and len(t) > 3:
            t = t[:-3]
        c["ticker_clean"] = t
    return candidates


def _fetch_history(ticker: str):
    """yfinance daily-close DataFrame around the broad window."""
    try:
        import yfinance as yf
    except ImportError:
        return None
    try:
        hist = yf.Ticker(ticker).history(period=YFINANCE_PERIOD, interval="1d", auto_adjust=False)
        if hist is None or hist.empty:
            return None
        return hist
    except Exception:
        return None


def _close_on_or_before(hist, target_date: str):
    """Closest available close on or BEFORE target_date. None if none."""
    if hist is None or hist.empty:
        return None
    try:
        target_ts = datetime.strptime(target_date, "%Y-%m-%d").date()
        idx = hist.index
        # idx is timezone-aware in yfinance; compare on date()
        eligible = hist[idx.date <= target_ts]
        if eligible.empty:
            return None
        return float(eligible["Close"].iloc[-1])
    except Exception:
        return None


def _close_on_or_after(hist, target_date: str):
    """Closest available close on or AFTER target_date."""
    if hist is None or hist.empty:
        return None
    try:
        target_ts = datetime.strptime(target_date, "%Y-%m-%d").date()
        idx = hist.index
        eligible = hist[idx.date >= target_ts]
        if eligible.empty:
            return None
        return float(eligible["Close"].iloc[0])
    except Exception:
        return None


def _close_n_trading_days_after(hist, filing_date: str, n: int):
    """The N-th trading day's close AFTER (and excluding) filing_date.

    "Trading days" = whatever yfinance returns in the period (already
    skips weekends/holidays). N=1 means the first row strictly after the
    filing date.
    """
    if hist is None or hist.empty:
        return None
    try:
        target_ts = datetime.strptime(filing_date, "%Y-%m-%d").date()
        idx = hist.index
        post = hist[idx.date > target_ts]
        if len(post) < n:
            return None
        return float(post["Close"].iloc[n - 1])
    except Exception:
        return None


def _pct(after, before):
    if before is None or after is None or before == 0:
        return None
    try:
        return round((after - before) / before * 100.0, 2)
    except Exception:
        return None


def compute_reactions(purchase: dict, hist) -> dict:
    """Returns a dict ready to upsert into backtest_reactions."""
    filing_date = purchase.get("filing_date")

    p_t_minus_1 = _close_on_or_before(
        hist,
        (datetime.strptime(filing_date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d"),
    )
    p_t_plus_0 = _close_on_or_after(hist, filing_date)
    p_t_plus_1 = _close_n_trading_days_after(hist, filing_date, 1)
    p_t_plus_5 = _close_n_trading_days_after(hist, filing_date, 5)
    p_t_plus_30 = _close_n_trading_days_after(hist, filing_date, 30)

    components = {"yfinance_period": YFINANCE_PERIOD}
    if p_t_minus_1 is None:
        components["skipped_reason"] = "no_baseline"

    return {
        "purchase_id": purchase.get("id"),
        "ticker": purchase["ticker_clean"],
        "company": purchase.get("company"),
        "filing_date": filing_date,
        "direction": purchase.get("direction"),
        "direction_confidence": purchase.get("direction_confidence"),
        "btc_amount": purchase.get("btc_amount"),
        "usd_amount": purchase.get("usd_amount"),
        "price_t_minus_1": p_t_minus_1,
        "price_t_plus_0": p_t_plus_0,
        "price_t_plus_1": p_t_plus_1,
        "price_t_plus_5": p_t_plus_5,
        "price_t_plus_30": p_t_plus_30,
        "reaction_1d_pct":  _pct(p_t_plus_1,  p_t_minus_1),
        "reaction_5d_pct":  _pct(p_t_plus_5,  p_t_minus_1),
        "reaction_30d_pct": _pct(p_t_plus_30, p_t_minus_1),
        "components": components,
    }


def main():
    purchases = _fetch_uncomputed_purchases(MAX_PURCHASES_PER_RUN)
    print(f"Eligible confirmed_purchases (last 730 days): {len(purchases)}")
    if not purchases:
        print("Nothing to backfill.")
        return

    # Dedupe by (ticker, filing_date) BEFORE per-ticker grouping. Several
    # confirmed_purchases can share a (ticker, filing_date) when a company
    # files multiple BTC events the same day. The backtest "event" is the
    # day's aggregate purchase — sum BTC + USD, keep highest-confidence
    # direction. Without this dedupe, the UNIQUE constraint on the target
    # table causes ON CONFLICT to fail mid-batch.
    deduped: dict[tuple[str, str], dict] = {}
    for p in purchases:
        key = (p["ticker_clean"], p["filing_date"])
        if key in deduped:
            existing = deduped[key]
            existing["btc_amount"] = (existing.get("btc_amount") or 0) + (p.get("btc_amount") or 0)
            existing["usd_amount"] = (existing.get("usd_amount") or 0) + (p.get("usd_amount") or 0)
            # Keep the direction with higher confidence; ties keep existing.
            new_conf = p.get("direction_confidence") or 0
            old_conf = existing.get("direction_confidence") or 0
            if new_conf > old_conf:
                existing["direction"] = p.get("direction")
                existing["direction_confidence"] = new_conf
            # Stick with the lowest-id purchase_id as the canonical link
            if (p.get("id") or 0) < (existing.get("id") or 1e18):
                existing["id"] = p.get("id")
        else:
            deduped[key] = dict(p)
    purchases = list(deduped.values())
    print(f"After dedupe by (ticker, filing_date): {len(purchases)} unique events")

    # Group by ticker so we fetch yfinance once per ticker, not per event
    by_ticker: dict[str, list[dict]] = {}
    for p in purchases:
        by_ticker.setdefault(p["ticker_clean"], []).append(p)
    print(f"Unique tickers to process: {len(by_ticker)}")

    rows_to_persist = []
    skipped_no_history = 0
    skipped_no_baseline = 0
    computed = 0

    for i, (ticker, ps) in enumerate(by_ticker.items()):
        if i and i % 20 == 0:
            print(f"  …processed {i}/{len(by_ticker)} tickers")
        hist = _fetch_history(ticker)
        if hist is None:
            skipped_no_history += len(ps)
            continue
        for p in ps:
            row = compute_reactions(p, hist)
            if row["price_t_minus_1"] is None:
                skipped_no_baseline += 1
                # Still persist the row so the page shows the event with
                # NULL reactions — explicit "we tried" > silent miss.
            rows_to_persist.append(row)
            computed += 1
        # Be polite to yfinance — small inter-ticker sleep
        time.sleep(0.3)

    print()
    print(f"Computed:  {computed} reactions")
    print(f"  with baseline:    {computed - skipped_no_baseline}")
    print(f"  no baseline (kept with NULL reactions): {skipped_no_baseline}")
    print(f"Skipped (no yfinance history at all): {skipped_no_history}")

    if not apply:
        print()
        print("Dry-run. Re-run with --apply to persist.")
        # Show a few sample rows
        for r in rows_to_persist[:3]:
            print(f"  sample: {r['ticker']} {r['filing_date']} direction={r.get('direction')} "
                  f"1d={r.get('reaction_1d_pct')} 5d={r.get('reaction_5d_pct')} 30d={r.get('reaction_30d_pct')}")
        return

    # Chunked upsert
    print()
    print("Upserting rows…")
    CHUNK = 200
    ok = fail = 0
    for i in range(0, len(rows_to_persist), CHUNK):
        batch = rows_to_persist[i : i + CHUNK]
        try:
            supabase.table("backtest_reactions").upsert(batch, on_conflict="ticker,filing_date").execute()
            ok += len(batch)
        except Exception as e:
            fail += len(batch)
            print(f"  ERROR chunk {i // CHUNK}: {e}")
    print(f"Upserted: {ok}, failed: {fail}")


if __name__ == "__main__":
    main()
