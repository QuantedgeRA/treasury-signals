"""
gov_entities.py — Fix government entity names AND BTC holdings after sync
--------------------------------------------------------------------------
The main scraper puts correct BTC amounts in the TICKER field (e.g. ₿328,372)
and wrong amounts in btc_holdings. This script:
1. Extracts the real BTC from the garbled ticker field
2. Assigns proper country names and tickers by rank
3. Also scrapes BitcoinTreasuries.net for supplemental data
4. Ensures entity_type = 'government'
"""

import os
import re
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from supabase import create_client
from logger import get_logger

logger = get_logger(__name__)

load_dotenv()

# Government entities ordered by expected BTC holdings (largest first)
GOVERNMENT_NAMES = [
    {'name': 'United States', 'ticker': 'US.GOV'},
    {'name': 'China', 'ticker': 'CN.GOV'},
    {'name': 'United Kingdom', 'ticker': 'GB.GOV'},
    {'name': 'Ukraine', 'ticker': 'UA.GOV'},
    {'name': 'El Salvador', 'ticker': 'SV.GOV'},
    {'name': 'Bhutan', 'ticker': 'BT.GOV'},
    {'name': 'Finland', 'ticker': 'FI.GOV'},
    {'name': 'Georgia', 'ticker': 'GE.GOV'},
    {'name': 'Venezuela', 'ticker': 'VE.GOV'},
    {'name': 'Liechtenstein', 'ticker': 'LI.GOV'},
    {'name': 'North Korea (DPRK)', 'ticker': 'KP.GOV'},
    {'name': 'Switzerland', 'ticker': 'CH.GOV'},
    {'name': 'UAE', 'ticker': 'AE.GOV'},
    {'name': 'Kazakhstan', 'ticker': 'KZ.GOV'},
    {'name': 'Taiwan', 'ticker': 'TW.GOV'},
]


def _extract_btc_from_ticker(ticker_str):
    """Extract BTC amount from garbled ticker like '₿328,372' or 'Â¿328,372'."""
    if not ticker_str:
        return 0
    # Remove ₿, Â, ¿ and other non-numeric chars, keep digits and commas
    clean = ticker_str.replace('\u20bf', '').replace('₿', '')
    clean = clean.replace('Â', '').replace('¿', '').replace('Â¿', '')
    clean = clean.replace(',', '').strip()
    clean = re.sub(r'[^\d.]', '', clean)
    try:
        return int(float(clean)) if clean else 0
    except:
        return 0


def _scrape_government_btc():
    """Fetch LIVE government BTC holdings from BitcoinTreasuries.net."""
    url = "https://bitcointreasuries.net/governments"
    try:
        resp = requests.get(url, timeout=30, headers={
            'User-Agent': 'Mozilla/5.0 (compatible; TreasuryBot/1.0)'
        })
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')

        # Collect all BTC amounts found on the page
        btc_amounts = []
        rows = soup.select('table tr')
        for row in rows:
            cells = row.find_all('td')
            if len(cells) < 2:
                continue
            texts = [td.get_text(strip=True) for td in cells]
            # Find the largest number in this row (likely BTC amount)
            max_btc = 0
            for t in texts:
                clean = t.replace('\u20bf', '').replace('₿', '').replace(',', '').replace(' ', '')
                clean = re.sub(r'[^\d.]', '', clean)
                try:
                    val = int(float(clean)) if clean else 0
                    if val > max_btc and val < 50_000_000:  # sanity check
                        max_btc = val
                except:
                    pass
            if max_btc > 0:
                btc_amounts.append(max_btc)

        # Sort descending — should match our GOVERNMENT_NAMES order
        btc_amounts.sort(reverse=True)
        logger.info(f"  Gov scrape: fetched {len(btc_amounts)} BTC amounts from website")
        return btc_amounts

    except Exception as e:
        logger.warning(f"  Gov scrape failed: {e}")
        return []


def fix_government_entities(supabase_client=None):
    """Fix government entity names, tickers, AND BTC holdings."""
    if supabase_client is None:
        SUPABASE_URL = os.getenv("SUPABASE_URL")
        SUPABASE_KEY = os.getenv("SUPABASE_KEY")
        supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)

    # Step 1: Try to get live BTC amounts from website
    live_btc_amounts = _scrape_government_btc()

    try:
        # Step 2: Get all government entities from database
        result = supabase_client.table("treasury_companies").select(
            "id, company, ticker, btc_holdings, entity_type, is_government"
        ).eq("is_government", True).execute()

        gov_rows = result.data or []
        if not gov_rows:
            logger.debug("Gov fix: no government entities found")
            return 0

        # Step 3: For each row, try to extract REAL BTC from the ticker field
        # The main scraper puts BTC amounts like "₿328,372" in the ticker
        for row in gov_rows:
            ticker_btc = _extract_btc_from_ticker(row.get("ticker", ""))
            if ticker_btc > 0:
                row["_real_btc"] = ticker_btc
            else:
                row["_real_btc"] = row.get("btc_holdings", 0) or 0

        # Sort by the REAL BTC amount (largest first)
        gov_rows.sort(key=lambda x: -x["_real_btc"])

        fixed = 0

        # Step 4: Assign names by rank position
        for i, row in enumerate(gov_rows):
            if i >= len(GOVERNMENT_NAMES):
                break

            gov = GOVERNMENT_NAMES[i]
            row_id = row["id"]
            current_name = row.get("company", "")

            # Determine best BTC amount:
            # Priority: 1) extracted from ticker field (most reliable), 2) live website, 3) existing db value
            if row["_real_btc"] > 0:
                best_btc = row["_real_btc"]
            elif i < len(live_btc_amounts) and live_btc_amounts[i] > 0:
                best_btc = row["_real_btc"]
            else:
                best_btc = row.get("btc_holdings", 0)

            # Update
            needs_update = (
                current_name != gov['name'] or
                row.get("btc_holdings", 0) != best_btc or
                row.get("entity_type") != "government"
            )

            if needs_update:
                supabase_client.table("treasury_companies").update({
                    "company": gov['name'],
                    "ticker": gov['ticker'],
                    "entity_type": "government",
                    "btc_holdings": best_btc,
                }).eq("id", row_id).execute()
                logger.info(f"  Gov fix: '{current_name}' → '{gov['name']}' ({best_btc:,} BTC)")
                fixed += 1

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
