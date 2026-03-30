"""
shares_updater.py — Auto-update shares outstanding from Yahoo Finance
----------------------------------------------------------------------
Updates the shares_outstanding column in treasury_companies for
publicly traded BTC holders. Runs after treasury_sync.

Usage:
    from shares_updater import update_shares
    update_shares()  # Call after treasury_sync.run()
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

# Ticker mapping: database ticker → Yahoo Finance ticker
TICKER_MAP = {
    'MSTR.US': 'MSTR',
    'MARA.US': 'MARA',
    'RIOT.US': 'RIOT',
    'CLSK.US': 'CLSK',
    'HUT.US': 'HUT',
    'COIN.US': 'COIN',
    'TSLA.US': 'TSLA',
    'XYZ.US': 'XYZ',
    'CORZ.US': 'CORZ',
    'BITF.US': 'BITF',
    'CIFR.US': 'CIFR',
    'WULF.US': 'WULF',
    'HIVE.US': 'HIVE',
    'GME.US': 'GME',
    'SMLR.US': 'SMLR',
    'GLXY.US': 'GLXY',
    'XXI.US': 'XXI',
    'DJT.US': 'DJT',
    'BTBT.US': 'BTBT',
    'ABTC.US': 'ABTC',
    'RUM.US': 'RUM',
    'BLSH.US': 'BLSH',
    'VIRT.US': 'VIRT',
}


def update_shares():
    """Update shares outstanding for major BTC holders from Yahoo Finance."""
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
    logger.info("Shares updater — manual run...")
    result = update_shares()
    print(f"Updated: {result['updated']}, Errors: {result['errors']}")
