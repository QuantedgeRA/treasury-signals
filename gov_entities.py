"""
gov_entities.py — Fix government entity names AND BTC holdings after sync
--------------------------------------------------------------------------
Scrapes BitcoinTreasuries.net/governments for BOTH name and BTC amount,
then matches each scraped entry to the garbled DB entry by BTC amount.

No more hardcoded rank order — adapts automatically when countries are
added, removed, or reordered on the website.
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

# Country name → ticker mapping (for clean ticker assignment)
# This doesn't need to be ordered — it's a lookup table, not a rank list
COUNTRY_TICKERS = {
    'united states': 'US.GOV',
    'china': 'CN.GOV',
    'united kingdom': 'GB.GOV',
    'ukraine': 'UA.GOV',
    'el salvador': 'SV.GOV',
    'united arab emirates': 'AE.GOV',
    'bhutan': 'BT.GOV',
    'finland': 'FI.GOV',
    'kazakhstan': 'KZ.GOV',
    'georgia': 'GE.GOV',
    'venezuela': 'VE.GOV',
    'liechtenstein': 'LI.GOV',
    'north korea': 'KP.GOV',
    'switzerland': 'CH.GOV',
    'taiwan': 'TW.GOV',
    'germany': 'DE.GOV',
    'russia': 'RU.GOV',
    'japan': 'JP.GOV',
    'brazil': 'BR.GOV',
    'canada': 'CA.GOV',
    'australia': 'AU.GOV',
    'india': 'IN.GOV',
    'norway': 'NO.GOV',
    'poland': 'PL.GOV',
    'thailand': 'TH.GOV',
    'singapore': 'SG.GOV',
    'iran': 'IR.GOV',
    'turkey': 'TR.GOV',
    'tonga': 'TO.GOV',
    'hong kong': 'HK.GOV',
    'ethiopia': 'ET.GOV',
    'colombia': 'CO.GOV',
    'czech': 'CZ.GOV',
    'czech republic': 'CZ.GOV',
    'montenegro': 'ME.GOV',
    'myanmar': 'MM.GOV',
    'saudi': 'SA.GOV',
    'saudi arabia': 'SA.GOV',
}


def _extract_btc_from_ticker(ticker_str):
    """Extract BTC amount from garbled ticker like '₿328,372' or 'Â¿328,372'."""
    if not ticker_str:
        return 0
    clean = ticker_str.replace('\u20bf', '').replace('₿', '')
    clean = clean.replace('Â', '').replace('¿', '').replace('Â¿', '')
    clean = clean.replace(',', '').strip()
    clean = re.sub(r'[^\d.]', '', clean)
    try:
        return int(float(clean)) if clean else 0
    except:
        return 0


def _scrape_government_data():
    """
    Fetch LIVE government BTC holdings from BitcoinTreasuries.net.
    Returns list of {"name": "United States", "btc": 328372} dicts.
    Extracts BOTH name and BTC from each row.
    """
    url = "https://bitcointreasuries.net/governments"
    try:
        resp = requests.get(url, timeout=30, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')

        entities = []
        rows = soup.select('table tr')
        for row in rows:
            cells = row.find_all('td')
            if len(cells) < 2:
                continue
            texts = [td.get_text(strip=True) for td in cells]

            # BTC: largest number < 50M (entity_name_fixer's proven approach)
            btc = 0
            for t in texts:
                clean = t.replace('\u20bf', '').replace('₿', '').replace(',', '').replace(' ', '')
                clean = re.sub(r'[^\d.]', '', clean)
                try:
                    val = int(float(clean)) if clean else 0
                    if val > btc and val < 50_000_000:
                        btc = val
                except:
                    pass

            if btc <= 0:
                continue

            # Name: longest text starting with ASCII letter
            name = ""
            for t in texts:
                stripped = t.strip()
                if (len(stripped) > len(name) and
                    stripped[0:1].isascii() and stripped[0:1].isalpha() and
                    not stripped.replace(',', '').replace('.', '').replace(' ', '').isdigit()):
                    name = stripped

            if name:
                # Clean parenthetical notes like "(holdings of public official..."
                name = re.sub(r'\(.*$', '', name).strip()
                entities.append({"name": name, "btc": btc})

        # Sort by BTC descending
        entities.sort(key=lambda x: -x["btc"])

        # Filter aggregate total: if largest ≈ sum of rest, remove it
        if len(entities) > 2:
            largest = entities[0]["btc"]
            rest_sum = sum(e["btc"] for e in entities[1:])
            if rest_sum > 0 and abs(largest - rest_sum) / rest_sum < 0.10:
                logger.debug(f"  Gov scrape: filtered aggregate total row ({largest:,} BTC)")
                entities = entities[1:]

        logger.info(f"  Gov scrape: fetched {len(entities)} governments from website")
        for e in entities[:5]:
            logger.debug(f"    {e['name']}: {e['btc']:,} BTC")
        return entities

    except Exception as e:
        logger.warning(f"  Gov scrape failed: {e}")
        return []


def _get_ticker_for_country(name):
    """Look up ticker for a country name."""
    name_lower = name.lower().strip()
    for key, ticker in COUNTRY_TICKERS.items():
        if key in name_lower:
            return ticker
    # Generate a fallback ticker
    clean = re.sub(r'[^A-Za-z]', '', name.upper()[:5])
    return f"{clean}.GOV" if clean else "UNK.GOV"


def _is_garbled(name):
    """Check if a name is garbled (non-ASCII first char or encoding artifacts)."""
    if not name:
        return True
    first = name[0]
    if not (first.isascii() and (first.isalpha() or first.isdigit())):
        return True
    if '\xc2' in name or '\xbf' in name or '\u20bf' in name:
        return True
    return False


def fix_government_entities(supabase_client=None):
    """Fix government entity names, tickers, AND BTC holdings."""
    if supabase_client is None:
        SUPABASE_URL = os.getenv("SUPABASE_URL")
        SUPABASE_KEY = os.getenv("SUPABASE_KEY")
        supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)

    # Step 1: Scrape name + BTC from website
    scraped = _scrape_government_data()

    try:
        # Step 2: Get all government entities from database
        result = supabase_client.table("treasury_companies").select(
            "id, company, ticker, btc_holdings, entity_type, is_government"
        ).eq("is_government", True).execute()

        gov_rows = result.data or []
        if not gov_rows:
            logger.debug("Gov fix: no government entities found")
            return 0

        # Step 3: Extract real BTC from ticker field for each garbled row
        garbled_rows = []
        for row in gov_rows:
            if _is_garbled(row.get("company", "")):
                ticker_btc = _extract_btc_from_ticker(row.get("ticker", ""))
                row["_real_btc"] = ticker_btc if ticker_btc > 0 else (row.get("btc_holdings", 0) or 0)
                garbled_rows.append(row)

        if not garbled_rows and not scraped:
            logger.debug("Gov fix: no garbled entries and no scraped data")
            return 0

        # Step 4: Match garbled DB entries to scraped entries by BTC AMOUNT
        # (same approach as entity_name_fixer — resilient to order changes)
        fixed = 0
        used_indices = set()

        for row in garbled_rows:
            row_btc = row["_real_btc"]
            if row_btc <= 0:
                continue

            row_id = row["id"]
            current_name = row.get("company", "")

            # Find closest BTC match from scraped data
            best_match = None
            best_match_idx = -1
            best_diff = float("inf")

            for j, candidate in enumerate(scraped):
                if j in used_indices:
                    continue

                diff = abs(row_btc - candidate["btc"])
                diff_pct = diff / max(row_btc, candidate["btc"], 1)

                # Must be within 30% tolerance
                if diff_pct <= 0.30 and diff < best_diff:
                    best_diff = diff
                    best_match = candidate
                    best_match_idx = j

            if best_match is None:
                logger.debug(f"  Gov fix: no match for garbled entry ({row_btc:,} BTC) — skipping")
                continue

            used_indices.add(best_match_idx)

            # Use scraped name and BTC
            clean_name = best_match["name"]
            best_btc = best_match["btc"]
            ticker = _get_ticker_for_country(clean_name)

            supabase_client.table("treasury_companies").update({
                "company": clean_name[:200],
                "ticker": ticker,
                "entity_type": "government",
                "is_government": True,
                "btc_holdings": best_btc,
            }).eq("id", row_id).execute()
            logger.info(f"  Gov fix: '{current_name}' → '{clean_name}' ({best_btc:,} BTC)")
            fixed += 1

        # Step 5: Also fix any clean-named entries that have wrong BTC
        # (match by name directly)
        if scraped:
            scraped_map = {e["name"].lower().strip(): e for e in scraped}
            for row in gov_rows:
                if row in garbled_rows:
                    continue  # Already handled
                name = row.get("company", "").strip()
                name_lower = name.lower()

                # Try to find this country in scraped data
                match = None
                for scraped_name, scraped_data in scraped_map.items():
                    if scraped_name in name_lower or name_lower in scraped_name:
                        match = scraped_data
                        break

                if match and row.get("btc_holdings", 0) != match["btc"]:
                    supabase_client.table("treasury_companies").update({
                        "btc_holdings": match["btc"],
                    }).eq("id", row["id"]).execute()
                    logger.debug(f"  Gov fix: updated BTC for {name}: {row.get('btc_holdings', 0):,} → {match['btc']:,}")
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
