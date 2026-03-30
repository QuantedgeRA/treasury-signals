"""
entity_name_fixer.py — Fix garbled ETF and Private Company names
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

PAGES = [
    {"url": "https://bitcointreasuries.net/etfs-and-exchanges", "entity_type": "etf", "label": "ETFs"},
    {"url": "https://bitcointreasuries.net/private-companies", "entity_type": "private_company", "label": "Private Companies"},
    {"url": "https://bitcointreasuries.net/defi-and-other", "entity_type": "defi", "label": "DeFi"},
]

# Known ticker suffixes to strip from concatenated names
KNOWN_TICKERS = [
    'IBIT', 'FBTC', 'GBTC', 'BTC', 'ARKB', 'BITB', 'HODL', 'BRRR', 'EZBC',
    'BTCO', 'BTCW', 'DEFI', 'QBTC', 'EBIT', 'BTCX', 'BITO', 'BITI', 'BTF',
]


def _clean_name(name):
    """Clean scraped name: remove concatenated tickers, fix encoding."""
    if not name:
        return name
    # Skip aggregate rows
    if name.lower().startswith('total'):
        return ""
    # Remove emoji/unicode junk at end
    name = re.sub(r'[\U0001f000-\U0001ffff]+', '', name).strip()
    # Remove concatenated ticker at end (e.g., "iShares Bitcoin TrustIBIT")
    for ticker in KNOWN_TICKERS:
        if name.endswith(ticker) and len(name) > len(ticker) + 3:
            name = name[:-len(ticker)].strip()
            break
    # Remove trailing ticker-like patterns (ALL CAPS at end)
    name = re.sub(r'([a-z])\s*([A-Z]{2,6})$', r'\1', name).strip()
    return name


def _scrape_page(url):
    """Scrape a BitcoinTreasuries.net page and return list of (name, btc) sorted by BTC desc."""
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

            name = ""
            btc = 0
            for t in texts:
                # Try as BTC amount
                clean = t.replace('\u20bf', '').replace('\u20bf', '').replace(',', '').replace(' ', '')
                clean = re.sub(r'[^\d.]', '', clean)
                try:
                    val = int(float(clean)) if clean else 0
                    if val > btc and val < 50_000_000:
                        btc = val
                except:
                    pass

                # Try as name
                stripped = t.strip()
                if (len(stripped) > len(name) and
                    stripped[0:1].isascii() and stripped[0:1].isalpha() and
                    not stripped.replace(',', '').replace('.', '').replace(' ', '').isdigit()):
                    name = stripped

            name = _clean_name(name)
            if btc > 0 and name:
                entities.append({"name": name, "btc": btc})

        entities.sort(key=lambda x: -x["btc"])
        return entities

    except Exception as e:
        logger.warning(f"  Name fix scrape failed for {url}: {e}")
        return []


def _extract_btc_from_ticker(ticker_str):
    """Extract BTC amount from garbled ticker like 'Â¿51,473'."""
    if not ticker_str:
        return 0
    clean = ticker_str.replace('\u20bf', '').replace('\u20bf', '')
    clean = clean.replace('\xc2', '').replace('\xbf', '')
    clean = clean.replace('Â', '').replace('¿', '')
    clean = clean.replace(',', '').strip()
    clean = re.sub(r'[^\d.]', '', clean)
    try:
        return int(float(clean)) if clean else 0
    except:
        return 0


def _is_garbled(name):
    """Check if a name is garbled (non-ASCII first char or contains encoding artifacts)."""
    if not name:
        return True
    first = name[0]
    # Must start with ASCII letter or digit
    if not (first.isascii() and (first.isalpha() or first.isdigit())):
        return True
    # Check for encoding artifacts
    if '\xc2' in name or '\xbf' in name or '\u20bf' in name:
        return True
    return False


def fix_entity_names(supabase_client=None):
    """Fix garbled names for ETFs, private companies, and DeFi entities."""
    if supabase_client is None:
        SUPABASE_URL = os.getenv("SUPABASE_URL")
        SUPABASE_KEY = os.getenv("SUPABASE_KEY")
        supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)

    total_fixed = 0

    for page in PAGES:
        entity_type = page["entity_type"]
        label = page["label"]

        # Step 1: Scrape proper names from website
        scraped = _scrape_page(page["url"])
        if not scraped:
            logger.debug(f"  Name fix: no data scraped for {label}")
            continue

        logger.info(f"  Name fix: scraped {len(scraped)} {label} from website")

        # Step 2: Get entities from database
        result = supabase_client.table("treasury_companies").select(
            "id, company, ticker, btc_holdings, entity_type"
        ).eq("entity_type", entity_type).execute()

        db_rows = result.data or []
        if not db_rows:
            continue

        # Step 3: Find garbled entries and extract real BTC from ticker
        garbled_rows = []
        for row in db_rows:
            if _is_garbled(row.get("company", "")):
                ticker_btc = _extract_btc_from_ticker(row.get("ticker", ""))
                row["_real_btc"] = ticker_btc if ticker_btc > 0 else (row.get("btc_holdings", 0) or 0)
                garbled_rows.append(row)

        if not garbled_rows:
            logger.debug(f"  Name fix: no garbled {label} found")
            continue

        # Sort garbled rows by real BTC descending
        garbled_rows.sort(key=lambda x: -x["_real_btc"])

        # Step 4: Match garbled rows to scraped names by rank
        # First, find which scraped names are NOT already in the DB with clean names
        clean_names = set()
        for row in db_rows:
            if not _is_garbled(row.get("company", "")):
                clean_names.add(row.get("company", "").lower().strip())

        # Filter scraped to only names not already used
        available_scraped = [s for s in scraped if s["name"].lower().strip() not in clean_names]

        fixed = 0
        for i, row in enumerate(garbled_rows):
            if i >= len(available_scraped):
                break

            target = available_scraped[i]
            current_name = row.get("company", "")
            best_btc = row["_real_btc"] if row["_real_btc"] > 0 else target["btc"]

            supabase_client.table("treasury_companies").update({
                "company": target["name"][:200],
                "btc_holdings": best_btc,
            }).eq("id", row["id"]).execute()
            logger.info(f"  Name fix: '{current_name[:20]}' → '{target['name']}' ({best_btc:,} BTC)")
            fixed += 1

        if fixed > 0:
            logger.info(f"  Name fix: {fixed} {label} updated")
        total_fixed += fixed

    if total_fixed > 0:
        logger.info(f"Name fix total: {total_fixed} entities updated")
    return total_fixed


if __name__ == "__main__":
    logger.info("Fixing entity names...")
    count = fix_entity_names()
    print(f"Fixed: {count}")
