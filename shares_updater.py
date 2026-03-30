"""
shares_updater.py — Auto-update shares outstanding from Yahoo Finance
----------------------------------------------------------------------
Dynamically queries ALL public companies from the database and fetches
shares outstanding from Yahoo Finance. No hardcoded ticker list.
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

# Special ticker mappings where database ticker differs from Yahoo Finance
# Only needed for tickers that don't match directly
TICKER_OVERRIDES = {
    'MPJPY': '3350.T',       # Metaplanet (Japan)
    'SQ2': 'XYZ',            # Block (formerly Square)
    'GLXY': 'GLXY.TO',       # Galaxy Digital (Toronto)
    'CS': 'CS.ST',           # CoinShares (Stockholm)
    'K33': 'K33.ST',         # K33 Research (Stockholm)
    'SRAG': 'SRAG.DE',       # Samara (Germany)
    'AKER': 'AKER.OL',       # Aker ASA (Oslo)
    'GEM': 'GEM.OL',         # Green Minerals (Oslo)
    'NBX': 'NBX.OL',         # Norwegian Block Exchange
    'FRAG': 'FRAG.ST',       # Fragbite Group (Stockholm)
    'VANA': 'VANA.MC',       # Vanadi Coffee (Madrid)
}


def get_yf_ticker(db_ticker):
    """Convert database ticker to Yahoo Finance ticker format."""
    # Check overrides first
    if db_ticker in TICKER_OVERRIDES:
        return TICKER_OVERRIDES[db_ticker]
    
    # Japanese tickers (4-digit numbers)
    if db_ticker.replace('.', '').isdigit() and len(db_ticker.split('.')[0]) == 4:
        return f"{db_ticker.split('.')[0]}.T"
    
    # Korean tickers (6-digit numbers)
    if db_ticker.replace('.', '').isdigit() and len(db_ticker.split('.')[0]) == 6:
        return f"{db_ticker.split('.')[0]}.KQ"
    
    # Hong Kong tickers
    if db_ticker.endswith('.HK'):
        return db_ticker
    
    # Australian tickers
    if db_ticker.endswith('.AX') or db_ticker.endswith('.AU'):
        return db_ticker
    
    # Canadian tickers
    if db_ticker.endswith('.V') or db_ticker.endswith('.TO') or db_ticker.endswith('.CN') or db_ticker.endswith('.NE'):
        return db_ticker
    
    # European tickers
    for suffix in ['.ST', '.OL', '.DE', '.MC', '.PA', '.DU', '.F', '.L', '.AS', '.IS', '.AQ', '.WA', '.BK', '.TA', '.SA']:
        if db_ticker.endswith(suffix):
            return db_ticker
    
    # US tickers — try as-is (most common case)
    return db_ticker


def update_shares():
    """Fetch all public companies from DB and update shares from Yahoo Finance."""
    logger.info("Shares updater: starting (all public companies)...")

    # Get all public companies from database
    result = supabase.table("treasury_companies").select(
        "id, ticker, company, entity_type, shares_outstanding"
    ).eq("entity_type", "public_company").gt("btc_holdings", 0).execute()

    companies = result.data or []
    logger.info(f"  Found {len(companies)} public companies to check")

    updated = 0
    errors = 0
    skipped = 0

    for company in companies:
        db_ticker = company.get("ticker", "")
        company_name = company.get("company", "")
        company_id = company.get("id")

        # Skip tickers that are obviously not Yahoo Finance compatible
        if not db_ticker or len(db_ticker) > 15:
            skipped += 1
            continue

        # Skip garbled tickers (must be ASCII letters/numbers/dots only)
        if not all(c.isascii() for c in db_ticker):
            skipped += 1
            continue
        if db_ticker.startswith('¿') or '¿' in db_ticker or '₿' in db_ticker:
            skipped += 1
            continue

        yf_ticker = get_yf_ticker(db_ticker)

        try:
            stock = yf.Ticker(yf_ticker)
            info = stock.info or {}

            shares = info.get('sharesOutstanding') or info.get('impliedSharesOutstanding') or 0

            if shares > 0:
                supabase.table("treasury_companies").update({
                    "shares_outstanding": int(shares),
                }).eq("id", company_id).execute()
                updated += 1
            else:
                errors += 1

            # Rate limit: don't hammer Yahoo Finance
            time.sleep(0.3)

        except Exception as e:
            errors += 1
            if errors <= 5:
                logger.debug(f"  Shares error for {db_ticker} ({yf_ticker}): {e}")

    logger.info(f"Shares updater: {updated} updated, {errors} errors, {skipped} skipped")
    return {"updated": updated, "errors": errors, "skipped": skipped}


if __name__ == "__main__":
    result = update_shares()
    print(f"Updated: {result['updated']}, Errors: {result['errors']}, Skipped: {result['skipped']}")
