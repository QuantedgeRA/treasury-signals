"""
entity_classifier.py — Fix entity_type classifications after treasury_sync
---------------------------------------------------------------------------
Fixes DeFi protocols, ETFs, and aggregate rows that BitcoinTreasuries.net
incorrectly labels as public_company.

Usage:
    from entity_classifier import fix_entity_types
    fix_entity_types(supabase)  # Call after treasury_sync.run()
"""

import os
from dotenv import load_dotenv
from supabase import create_client
from logger import get_logger

logger = get_logger(__name__)

load_dotenv()

# Tickers that should be classified as 'defi' (DeFi protocols, wrapped tokens, bridges)
DEFI_TICKERS = [
    'BTC',          # Wrapped BTC (WBTC)
    'BTCB',         # Binance Wrapped BTC
    'SOLVPROTO',    # Solv Protocol Bitcoin
    'LOMBARDPR',    # Lombard Protocol (LBTC)
    'AVALANCHE',    # Avalanche Bridged Bitcoin
    'CBBTC',        # Coinbase Wrapped BTC
    'DLCBTC',       # DLC.Link BTC
    'TBTC',         # Threshold BTC
    'KBTC',         # Kintsugi BTC
    'RBTC',         # RSK Smart Bitcoin
    'RENBTC',       # Ren BTC
    'SBTC',         # Synth BTC
    'PBTC',         # pTokens BTC
    'OBTC',         # BoringDAO BTC
]

# Keywords in company names that indicate DeFi protocols
DEFI_KEYWORDS = [
    'wrapped', 'bridge', 'bridged', 'protocol', 'vault', 
    'staking', 'lending', 'liquidity', 'synthetic',
    'pegged', 'tokenized',
]

# Aggregate/summary rows that should be deleted (not real entities)
DELETE_NAMES = ['Total:', 'Total', 'Grand Total']

# Tickers that should be classified as 'etf'
ETF_KEYWORDS = ['etf', 'trust', 'fund', 'ishares', 'proshares', 'grayscale', 'bitwise']


def fix_entity_types(supabase_client=None):
    """Fix entity_type for DeFi protocols, ETFs, and remove aggregate rows."""
    if supabase_client is None:
        SUPABASE_URL = os.getenv("SUPABASE_URL")
        SUPABASE_KEY = os.getenv("SUPABASE_KEY")
        supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)

    fixed = 0

    try:
        # 1. Delete aggregate/summary rows (not real entities)
        for name in DELETE_NAMES:
            result = supabase_client.table("treasury_companies").delete().eq("company", name).execute()
            if result.data:
                logger.info(f"  Entity fix: deleted aggregate row '{name}'")
                fixed += len(result.data)

        # 2. Fix known DeFi tickers
        for ticker in DEFI_TICKERS:
            result = supabase_client.table("treasury_companies").update({
                "entity_type": "defi"
            }).eq("ticker", ticker).neq("entity_type", "defi").execute()
            if result.data:
                for row in result.data:
                    logger.info(f"  Entity fix: {row.get('company', ticker)} → defi")
                fixed += len(result.data)

        # 3. Fix by keyword matching (company name contains DeFi-related terms)
        result = supabase_client.table("treasury_companies").select(
            "id, company, ticker, entity_type"
        ).eq("entity_type", "public_company").execute()

        for row in (result.data or []):
            name_lower = (row.get("company") or "").lower()
            
            # Check DeFi keywords
            if any(kw in name_lower for kw in DEFI_KEYWORDS):
                supabase_client.table("treasury_companies").update({
                    "entity_type": "defi"
                }).eq("id", row["id"]).execute()
                logger.info(f"  Entity fix: '{row['company']}' → defi (keyword match)")
                fixed += 1

        if fixed > 0:
            logger.info(f"Entity fix: {fixed} entities corrected")
        return fixed

    except Exception as e:
        logger.error(f"Entity fix error: {e}")
        return 0


if __name__ == "__main__":
    logger.info("Fixing entity types...")
    count = fix_entity_types()
    print(f"Fixed: {count}")
