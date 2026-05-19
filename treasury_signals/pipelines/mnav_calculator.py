"""
mnav_calculator.py — cross-company mNAV (premium-to-NAV) tracker.

mNAV = (market cap) / (BTC holdings × BTC price)

Above 1.0 = the market values the company at a premium to its raw BTC stash
(typical for MSTR, which has historically traded at 1.5–3x). Below 1.0 =
discount. Premium compression on a leveraged-BTC equity like MSTR is a
classic warning sign even when BTC itself is flat — the trade is selling
the company faster than the BTC backing it.

Currently BitcoinQuant covers this depth for MSTR only. This module extends
the playbook to every treasury company with the four inputs we have:
  • btc_holdings        — from treasury_companies (BitcoinTreasuries sync)
  • shares_outstanding  — from treasury_companies (Yahoo Finance 6am sync)
  • stock_price         — fetched per-batch from Yahoo Finance
  • btc_price           — leaderboard_snapshots latest

Called once per day from post_scan.run_heavy_maintenance (6am only, after
the shares_outstanding sync completes). Writes one row per ticker per day
into mnav_history (migration 0014) for trend queries on the dashboard
`/mnav` page.

Defensive design:
  • Skip companies with btc_holdings ≤ 0 (irrelevant) or shares_outstanding ≤ 0
    (data not yet synced; common for newly-added entities).
  • Skip companies whose stock price yfinance can't fetch (foreign tickers
    without a US ADR, delisted, etc.); log + continue. Failures don't block
    the rest of the batch.
  • Per-ticker try/except so one bad ticker doesn't kill the whole run.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv
from supabase import create_client

from treasury_signals.logger import get_logger
from treasury_signals.observability import capture_exception

logger = get_logger(__name__)
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

# Hard caps so one mNAV run never balloons cost / time.
MAX_COMPANIES_PER_RUN = 250  # we currently track ~200; headroom for growth
MIN_BTC_HOLDINGS = 1          # noise floor; sub-1 BTC entries are stale data


@dataclass
class MnavResult:
    """Structured output of compute_mnav_for_company."""

    ticker: str
    company: str
    snapshot_date: str           # YYYY-MM-DD
    mnav: float                  # ratio, e.g. 2.31 = trading at 2.31× BTC value
    premium_pct: float           # (mnav - 1) × 100, signed
    market_cap_usd: float
    btc_value_usd: float
    btc_holdings: int
    shares_outstanding: int
    stock_price: float
    btc_price: float
    skipped_reason: Optional[str] = None  # set when mNAV couldn't be computed


def compute_mnav_for_company(
    company: dict,
    btc_price: float,
    stock_price: float,
    snapshot_date: Optional[str] = None,
) -> MnavResult:
    """Pure function: given a treasury_companies row + market context, compute mNAV.

    Caller fetches stock_price (yfinance) and btc_price (leaderboard_snapshots)
    once for the whole batch — this function is just the math, so it's trivially
    testable.
    """
    snapshot_date = snapshot_date or datetime.now().strftime("%Y-%m-%d")
    ticker = (company.get("ticker") or "").upper()
    name = company.get("company") or ticker
    btc_holdings = int(company.get("btc_holdings") or 0)
    shares = int(company.get("shares_outstanding") or 0)

    base = MnavResult(
        ticker=ticker,
        company=name,
        snapshot_date=snapshot_date,
        mnav=0.0,
        premium_pct=0.0,
        market_cap_usd=0.0,
        btc_value_usd=0.0,
        btc_holdings=btc_holdings,
        shares_outstanding=shares,
        stock_price=stock_price,
        btc_price=btc_price,
    )

    if btc_holdings < MIN_BTC_HOLDINGS:
        base.skipped_reason = "btc_holdings below noise floor"
        return base
    if shares <= 0:
        base.skipped_reason = "shares_outstanding missing"
        return base
    if stock_price <= 0:
        base.skipped_reason = "stock_price unavailable"
        return base
    if btc_price <= 0:
        base.skipped_reason = "btc_price unavailable"
        return base

    market_cap = shares * stock_price
    btc_value = btc_holdings * btc_price
    if btc_value <= 0:
        base.skipped_reason = "btc_value zero (data inconsistency)"
        return base

    mnav = market_cap / btc_value
    base.market_cap_usd = market_cap
    base.btc_value_usd = btc_value
    base.mnav = mnav
    base.premium_pct = (mnav - 1.0) * 100.0
    return base


# ─── Stock-price batching ─────────────────────────────────────────────────


def _fetch_stock_prices(tickers: list[str]) -> dict[str, float]:
    """Fetch latest close for a batch of tickers via yfinance.

    Returns {ticker_upper: price}. Tickers that fail return as 0.0 — caller
    sees them as 'stock_price unavailable' and skips. Designed for the 6am
    batch where 200 tickers go through in one yfinance call.
    """
    try:
        import yfinance as yf
    except ImportError:
        logger.warning("mnav: yfinance not installed — skipping stock price fetch")
        return {}

    if not tickers:
        return {}

    # yfinance batch download accepts space-separated tickers
    prices: dict[str, float] = {}
    # Process in chunks of 50 so one bad ticker doesn't poison the whole batch
    CHUNK = 50
    for i in range(0, len(tickers), CHUNK):
        chunk = tickers[i : i + CHUNK]
        try:
            data = yf.download(
                tickers=" ".join(chunk),
                period="2d",
                interval="1d",
                progress=False,
                group_by="ticker",
                threads=True,
            )
            for t in chunk:
                try:
                    if len(chunk) == 1:
                        # Single-ticker frame has flat columns, not grouped
                        close = data.get("Close")
                    else:
                        close = data[t]["Close"] if t in data.columns.get_level_values(0) else None
                    if close is None:
                        prices[t] = 0.0
                        continue
                    series = close.dropna()
                    prices[t] = float(series.iloc[-1]) if not series.empty else 0.0
                except Exception:
                    prices[t] = 0.0
        except Exception as e:
            logger.warning(f"mnav: yfinance chunk {i//CHUNK} failed: {e}")
            for t in chunk:
                prices.setdefault(t, 0.0)
    return prices


def _fetch_latest_btc_price() -> float:
    """Pull the latest BTC price from leaderboard_snapshots."""
    if not supabase:
        return 0.0
    try:
        res = (
            supabase.table("leaderboard_snapshots")
            .select("btc_price, snapshot_date")
            .gt("btc_price", 0)
            .order("snapshot_date", desc=True)
            .limit(1)
            .execute()
        )
        if res.data:
            return float(res.data[0].get("btc_price") or 0)
    except Exception as e:
        logger.warning(f"mnav: btc_price fetch failed: {e}")
    return 0.0


# ─── Batch driver ─────────────────────────────────────────────────────────


def compute_and_persist_all_mnav(btc_price_override: Optional[float] = None) -> dict:
    """Run mNAV computation across all tracked treasury companies + persist.

    Call from post_scan once per day (6am — when shares_outstanding is fresh).
    Returns a stats dict: {'computed', 'skipped', 'persisted', 'errors'}.
    """
    if not supabase:
        logger.warning("mnav: supabase client unconfigured — skipping run")
        return {"computed": 0, "skipped": 0, "persisted": 0, "errors": 0}

    btc_price = btc_price_override if btc_price_override else _fetch_latest_btc_price()
    if btc_price <= 0:
        logger.warning("mnav: no usable BTC price — skipping run entirely")
        return {"computed": 0, "skipped": 0, "persisted": 0, "errors": 0}

    try:
        # Public companies only — governments/DeFi/private don't have stock prices.
        res = (
            supabase.table("treasury_companies")
            .select("ticker, company, btc_holdings, shares_outstanding, entity_type")
            .gte("btc_holdings", MIN_BTC_HOLDINGS)
            .eq("entity_type", "public_company")
            .gt("shares_outstanding", 0)
            .limit(MAX_COMPANIES_PER_RUN)
            .execute()
        )
        companies = res.data or []
    except Exception as e:
        logger.error(f"mnav: companies fetch failed: {e}")
        capture_exception(e, context={"where": "mnav.compute_and_persist_all_mnav.fetch_companies"})
        return {"computed": 0, "skipped": 0, "persisted": 0, "errors": 1}

    if not companies:
        logger.info("mnav: no eligible companies")
        return {"computed": 0, "skipped": 0, "persisted": 0, "errors": 0}

    tickers = [c["ticker"].upper() for c in companies if c.get("ticker")]
    prices = _fetch_stock_prices(tickers)

    snapshot_date = datetime.now().strftime("%Y-%m-%d")
    computed = 0
    skipped = 0
    persisted = 0
    errors = 0

    for c in companies:
        ticker = (c.get("ticker") or "").upper()
        stock_price = prices.get(ticker, 0.0)
        try:
            result = compute_mnav_for_company(c, btc_price, stock_price, snapshot_date)
        except Exception as e:
            errors += 1
            logger.warning(f"mnav: compute failed for {ticker}: {e}")
            continue

        if result.skipped_reason:
            skipped += 1
            continue

        computed += 1

        # Persist (column names match migrations/0014_mnav_history.sql)
        try:
            supabase.table("mnav_history").upsert(
                {
                    "ticker": ticker,
                    "company": result.company,
                    "snapshot_date": snapshot_date,
                    "shares_outstanding": result.shares_outstanding,
                    "stock_price": round(result.stock_price, 4),
                    "btc_holdings": result.btc_holdings,
                    "btc_price": round(result.btc_price, 2),
                    "market_cap": round(result.market_cap_usd, 2),
                    "btc_value": round(result.btc_value_usd, 2),
                    "mnav": round(result.mnav, 4),
                    "components": {
                        "stock_source": "yfinance",
                        "btc_source": "leaderboard_snapshots",
                    },
                },
                on_conflict="ticker,snapshot_date",
            ).execute()
            persisted += 1
        except Exception as e:
            errors += 1
            logger.warning(f"mnav: persist failed for {ticker}: {e}")
            capture_exception(e, context={
                "where": "mnav.compute_and_persist_all_mnav.persist",
                "ticker": ticker,
            })

    logger.info(
        f"mNAV daily: {computed} computed, {skipped} skipped, {persisted} persisted, {errors} errors"
    )
    return {"computed": computed, "skipped": skipped, "persisted": persisted, "errors": errors}


# ─── Manual smoke test ────────────────────────────────────────────────────


if __name__ == "__main__":
    # Pure-function smoke test (no network calls)
    mstr_like = {
        "ticker": "MSTR",
        "company": "Strategy",
        "btc_holdings": 528185,
        "shares_outstanding": 280_000_000,
    }
    r = compute_mnav_for_company(mstr_like, btc_price=68000, stock_price=400)
    print(f"MSTR-like sample:")
    print(f"  market_cap: ${r.market_cap_usd / 1e9:.2f}B")
    print(f"  btc_value:  ${r.btc_value_usd / 1e9:.2f}B")
    print(f"  mnav:       {r.mnav:.3f}")
    print(f"  premium:    {r.premium_pct:+.2f}%")

    print("\nLive run (requires SUPABASE_* + yfinance network access):")
    stats = compute_and_persist_all_mnav()
    print(stats)
