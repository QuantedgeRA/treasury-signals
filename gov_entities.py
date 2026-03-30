"""
gov_entities.py — Government/Sovereign Entity Name Mapping
-----------------------------------------------------------
Post-processing for treasury_sync.py to fix garbled government names
from BitcoinTreasuries.net scraping (emoji flags → proper country names).

Usage:
    from gov_entities import fix_government_entities
    fix_government_entities(supabase)  # Call after treasury_sync.run()
"""

import os
from dotenv import load_dotenv
from supabase import create_client
from logger import get_logger

logger = get_logger(__name__)

load_dotenv()

# Known government BTC holders — maps approximate BTC holdings to proper names
# These are updated manually when new governments are confirmed
GOVERNMENT_ENTITIES = {
    # country_name, ticker, approximate BTC (used for matching)
    'United States': {'ticker': 'US.GOV', 'min_btc': 15000, 'max_btc': 500000},
    'China': {'ticker': 'CN.GOV', 'min_btc': 10000, 'max_btc': 250000},
    'United Kingdom': {'ticker': 'GB.GOV', 'min_btc': 3000, 'max_btc': 100000},
    'Ukraine': {'ticker': 'UA.GOV', 'min_btc': 2000, 'max_btc': 60000},
    'El Salvador': {'ticker': 'SV.GOV', 'min_btc': 300, 'max_btc': 10000},
    'Bhutan': {'ticker': 'BT.GOV', 'min_btc': 200, 'max_btc': 15000},
    'Finland': {'ticker': 'FI.GOV', 'min_btc': 100, 'max_btc': 8000},
    'Georgia': {'ticker': 'GE.GOV', 'min_btc': 100, 'max_btc': 6000},
    'Venezuela': {'ticker': 'VE.GOV', 'min_btc': 20, 'max_btc': 2000},
    'Liechtenstein': {'ticker': 'LI.GOV', 'min_btc': 5, 'max_btc': 500},
    'North Korea (DPRK)': {'ticker': 'KP.GOV', 'min_btc': 5, 'max_btc': 500},
    'Switzerland': {'ticker': 'CH.GOV', 'min_btc': 1, 'max_btc': 200},
}


def fix_government_entities(supabase_client=None):
    """
    Fix government entity names after treasury sync.
    Replaces garbled emoji names with proper country names.
    Also ensures entity_type = 'government' for all government rows.
    """
    if supabase_client is None:
        SUPABASE_URL = os.getenv("SUPABASE_URL")
        SUPABASE_KEY = os.getenv("SUPABASE_KEY")
        supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)

    try:
        # Get all government entities
        result = supabase_client.table("treasury_companies").select(
            "id, company, ticker, btc_holdings, entity_type, is_government"
        ).eq("is_government", True).execute()

        gov_rows = result.data or []
        if not gov_rows:
            logger.debug("Gov fix: no government entities found")
            return 0

        # Sort by btc_holdings descending to match by rank
        gov_rows.sort(key=lambda x: -(x.get("btc_holdings", 0) or 0))

        # Also sort our known list by approximate BTC descending
        known_sorted = sorted(
            GOVERNMENT_ENTITIES.items(),
            key=lambda x: -x[1]['max_btc']
        )

        fixed = 0
        for row in gov_rows:
            row_btc = row.get("btc_holdings", 0) or 0
            row_id = row["id"]
            current_name = row.get("company", "")
            current_ticker = row.get("ticker", "")

            # Check if already properly named
            if current_name in GOVERNMENT_ENTITIES:
                # Just ensure entity_type is correct
                if row.get("entity_type") != "government":
                    supabase_client.table("treasury_companies").update({
                        "entity_type": "government"
                    }).eq("id", row_id).execute()
                    fixed += 1
                continue

            # Try to match by BTC range
            matched = False
            for country_name, info in known_sorted:
                # Check if this country's ticker is already assigned to another row
                already_used = any(
                    r.get("company") == country_name
                    for r in gov_rows if r["id"] != row_id
                )
                if already_used:
                    continue

                if info['min_btc'] <= row_btc <= info['max_btc']:
                    supabase_client.table("treasury_companies").update({
                        "company": country_name,
                        "ticker": info['ticker'],
                        "entity_type": "government",
                    }).eq("id", row_id).execute()
                    logger.info(f"  Gov fix: '{current_name}' → '{country_name}' ({row_btc} BTC)")
                    fixed += 1
                    matched = True
                    # Update local reference
                    row["company"] = country_name
                    break

            if not matched:
                # Ensure entity_type is at least correct
                if row.get("entity_type") != "government":
                    supabase_client.table("treasury_companies").update({
                        "entity_type": "government"
                    }).eq("id", row_id).execute()
                    fixed += 1
                if current_name and not current_name[0].isalpha():
                    logger.warning(f"  Gov fix: unmatched entity '{current_name}' with {row_btc} BTC")

        if fixed > 0:
            logger.info(f"Gov fix: {fixed} government entities updated")
        return fixed

    except Exception as e:
        logger.error(f"Gov fix error: {e}")
        return 0


if __name__ == "__main__":
    logger.info("Fixing government entities...")
    count = fix_government_entities()
    print(f"Fixed: {count}")
