"""
shares_sync.py — Shares Outstanding Auto-Sync
================================================
Fetches shares outstanding from Yahoo Finance for all public companies
in treasury_companies and updates the database.

Runs once daily (called from main.py in the morning scan).
Only updates public companies with a valid ticker.

Usage:
    from shares_sync import sync_shares_outstanding
    sync_shares_outstanding()
"""

import os
import time
import yfinance as yf
from dotenv import load_dotenv
from supabase import create_client
from logger import get_logger

logger = get_logger(__name__)
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Exchange suffix stripping for Yahoo Finance lookups
EXCHANGE_SUFFIXES = ['.US', '.L', '.TO', '.AX', '.DE', '.PA', '.SW', '.HK', '.KS', '.SS', '.SZ', '.SA', '.V', '.ST', '.CO', '.MI', '.BR', '.MC', '.OL', '.HE', '.IS']


def _to_yahoo_ticker(db_ticker):
    """Convert database ticker to Yahoo Finance ticker."""
    if not db_ticker:
        return None
    t = db_ticker.strip()
    # .T tickers (Japan) work as-is on Yahoo
    if t.endswith('.T'):
        return t
    # Strip exchange suffixes
    for suffix in EXCHANGE_SUFFIXES:
        if t.upper().endswith(suffix):
            return t[:-len(suffix)]
    return t


def sync_shares_outstanding(limit=50):
    """
    Fetch shares outstanding from Yahoo Finance for public companies
    and update treasury_companies.

    Only processes companies where:
    - entity_type is public_company
    - btc_holdings > 0
    - ticker is not empty

    Args:
        limit: max companies to update per run (rate limit friendly)
    """
    logger.info("Shares sync: fetching shares outstanding from Yahoo Finance...")

    try:
        # Get public companies without shares data, or with stale data
        result = supabase.table("treasury_companies").select(
            "id, company, ticker, btc_holdings, shares_outstanding"
        ).eq("entity_type", "public_company").gt("btc_holdings", 0).execute()

        if not result.data:
            logger.info("Shares sync: no public companies found")
            return {"updated": 0, "failed": 0, "skipped": 0}

        # Prioritize companies without shares data
        companies = sorted(result.data, key=lambda c: 0 if not c.get('shares_outstanding') else 1)
        companies = companies[:limit]

        updated = 0
        failed = 0
        skipped = 0

        for company in companies:
            db_ticker = company.get('ticker', '')
            if not db_ticker:
                skipped += 1
                continue

            yahoo_ticker = _to_yahoo_ticker(db_ticker)
            if not yahoo_ticker:
                skipped += 1
                continue

            try:
                stock = yf.Ticker(yahoo_ticker)
                info = stock.info or {}

                shares = info.get('sharesOutstanding', 0) or info.get('impliedSharesOutstanding', 0) or 0

                if shares and shares > 0:
                    current_shares = company.get('shares_outstanding') or 0

                    # Only update if meaningfully different (>1% change or currently 0)
                    if current_shares == 0 or abs(shares - current_shares) / max(current_shares, 1) > 0.01:
                        supabase.table("treasury_companies").update({
                            "shares_outstanding": int(shares),
                        }).eq("id", company["id"]).execute()

                        name = company.get('company', '')[:25]
                        logger.info(f"  Shares: {name} ({db_ticker}) — {current_shares:,} → {int(shares):,}")
                        updated += 1
                    else:
                        skipped += 1
                else:
                    failed += 1

                time.sleep(0.5)  # Rate limit
            except Exception as e:
                logger.debug(f"  Shares: {db_ticker} failed — {e}")
                failed += 1
                time.sleep(0.3)

        logger.info(f"Shares sync: {updated} updated, {failed} failed, {skipped} skipped")
        return {"updated": updated, "failed": failed, "skipped": skipped}

    except Exception as e:
        logger.error(f"Shares sync error: {e}")
        return {"updated": 0, "failed": 0, "skipped": 0}


if __name__ == "__main__":
    logger.info("Shares sync — manual run...")
    result = sync_shares_outstanding(limit=20)
    print(f"Updated: {result['updated']}, Failed: {result['failed']}, Skipped: {result['skipped']}")
