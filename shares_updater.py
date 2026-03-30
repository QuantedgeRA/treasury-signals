"""
shares_updater.py — Auto-update shares outstanding from Yahoo Finance
"""

import os
import yfinance as yf
from dotenv import load_dotenv
from supabase import create_client
from logger import get_logger

logger = get_logger(__name__)

load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Database ticker → Yahoo Finance ticker
TICKER_MAP = {
    'MSTR': 'MSTR', 'MARA': 'MARA', 'RIOT': 'RIOT', 'CLSK': 'CLSK',
    'HUT': 'HUT', 'COIN': 'COIN', 'TSLA': 'TSLA', 'CORZ': 'CORZ',
    'BITF': 'BITF', 'CIFR': 'CIFR', 'WULF': 'WULF', 'HIVE': 'HIVE',
    'GME': 'GME', 'SMLR': 'SMLR', 'XXI': 'XXI', 'DJT': 'DJT',
    'BTBT': 'BTBT', 'ABTC': 'ABTC', 'RUM': 'RUM', 'BLSH': 'BLSH',
    'VIRT': 'VIRT', 'CEPO': 'CEPO',
}

def update_shares():
    logger.info("Shares updater: starting...")
    updated = 0
    errors = 0
    for db_ticker, yf_ticker in TICKER_MAP.items():
        try:
            stock = yf.Ticker(yf_ticker)
            info = stock.info or {}
            shares = info.get('sharesOutstanding') or info.get('impliedSharesOutstanding') or 0
            if shares > 0:
                supabase.table("treasury_companies").update({
                    "shares_outstanding": int(shares),
                }).eq("ticker", db_ticker).execute()
                updated += 1
            else:
                errors += 1
                if errors <= 3:
                    logger.debug(f"  No shares data for {yf_ticker}")
        except Exception as e:
            errors += 1
            if errors <= 3:
                logger.debug(f"  Shares error for {yf_ticker}: {e}")
    logger.info(f"Shares updater: {updated} updated, {errors} errors")
    return {"updated": updated, "errors": errors}

if __name__ == "__main__":
    result = update_shares()
    print(f"Updated: {result['updated']}, Errors: {result['errors']}")
