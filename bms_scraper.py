"""
bms_scraper.py — BitcoinMiningStock.io Treasury Data Scraper
==============================================================
Third aggregator source alongside CoinGecko and BitcoinTreasuries.net.
169 verified public companies with manual review from primary sources.

SAFETY: Never updates if new value is >3x or <0.3x current value.
This prevents bad parsing from corrupting data.

Usage:
    from bms_scraper import sync_bms_data
    sync_bms_data()  # Call every 6 hours
"""

import os
import re
import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from dotenv import load_dotenv
from supabase import create_client
from logger import get_logger

logger = get_logger(__name__)
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

BMS_TREASURIES_URL = "https://bitcoinminingstock.io/bitcoin-treasuries"
BMS_MINERS_URL = "https://bitcoinminingstock.io/miner-treasuries"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}

SOURCE_PRIORITY = {
    'sec_filing': 100, 'regulatory_filing': 90, 'etf_issuer': 85,
    'government_official': 80, 'defi_onchain': 80, 'bms_verified': 70,
    'press_release': 60, 'aggregator': 10,
}


def _parse_number(text):
    """Parse a number, being very strict about what we accept."""
    if not text:
        return 0
    clean = text.replace(',', '').replace(' ', '').strip()
    # Only accept strings that are purely numeric (with optional decimal)
    if not re.match(r'^\d+\.?\d*$', clean):
        return 0
    try:
        return float(clean) if '.' in clean else int(clean)
    except:
        return 0


def _scrape_treasury_page(url):
    """Scrape a BMS treasury page. Extract ONLY from clearly structured table cells."""
    entities = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')

        tables = soup.find_all('table')
        if not tables:
            logger.debug(f"  BMS: no tables found on {url}")
            return entities

        main_table = max(tables, key=lambda t: len(t.find_all('tr')))
        rows = main_table.find_all('tr')
        if len(rows) < 2:
            return entities

        # Parse header
        header_cells = rows[0].find_all(['th', 'td'])
        headers = [th.get_text(strip=True).lower() for th in header_cells]

        # Find column indices strictly
        name_idx = None
        ticker_idx = None
        btc_idx = None

        for i, h in enumerate(headers):
            h_clean = h.strip()
            if h_clean in ('company', 'name', 'company name'):
                name_idx = i
            elif h_clean in ('ticker', 'symbol'):
                ticker_idx = i
            elif 'btc' in h_clean and any(kw in h_clean for kw in ['hold', 'treasury', 'amount', 'total']):
                btc_idx = i
            elif h_clean == 'btc' or h_clean == 'btc holdings':
                btc_idx = i

        if btc_idx is None:
            logger.debug(f"  BMS: could not find BTC column. Headers: {headers}")
            return entities

        # Parse rows — strict cell-by-cell extraction
        for row in rows[1:]:
            cells = row.find_all(['td', 'th'])
            if len(cells) <= max(filter(None, [name_idx, ticker_idx, btc_idx]), default=0):
                continue

            # Get text from INDIVIDUAL cells only
            name = ''
            ticker = ''
            btc = 0

            if name_idx is not None and name_idx < len(cells):
                name = cells[name_idx].get_text(strip=True)
            if ticker_idx is not None and ticker_idx < len(cells):
                ticker = cells[ticker_idx].get_text(strip=True).upper()
            if btc_idx is not None and btc_idx < len(cells):
                btc_text = cells[btc_idx].get_text(strip=True)
                btc = _parse_number(btc_text)

            # If no name column found, try first cell
            if not name and cells:
                first_text = cells[0].get_text(strip=True)
                if first_text and first_text[0:1].isalpha():
                    name = first_text

            # Separate ticker from name if concatenated (e.g., "Galaxy DigitalGLXY")
            if name and not ticker:
                # Check if name ends with what looks like a ticker
                match = re.search(r'([A-Z]{2,5}(?:\.[A-Z]{1,2})?)$', name)
                if match:
                    possible_ticker = match.group(1)
                    possible_name = name[:match.start()].strip()
                    if possible_name and len(possible_name) > 3:
                        ticker = possible_ticker
                        name = possible_name

            # Validate: BTC must be reasonable (1 to 800,000)
            if name and 1 <= btc <= 800_000:
                entities.append({
                    'company': name[:200],
                    'ticker': ticker[:20],
                    'btc_holdings': int(btc),
                })

        logger.info(f"  BMS: scraped {len(entities)} entities from {url.split('/')[-1]}")

    except Exception as e:
        logger.debug(f"  BMS scrape error for {url}: {e}")

    return entities


def _match_entity(bms_entity, db_entities):
    """Find matching entity in database."""
    ticker = bms_entity.get('ticker', '').upper().strip()
    name = bms_entity.get('company', '').lower().strip()

    if ticker:
        for db in db_entities:
            db_ticker = (db.get('ticker', '') or '').upper().strip()
            if db_ticker == ticker or db_ticker.replace('.US', '') == ticker:
                return db

    if name and len(name) > 5:
        for db in db_entities:
            db_name = (db.get('company', '') or '').lower().strip()
            if db_name == name:
                return db
            if name[:15] in db_name or db_name[:15] in name:
                return db

    return None


def sync_bms_data():
    """
    Main function: Scrape BMS and cross-validate/update entities.
    SAFETY: Never updates if new value differs by more than 3x from current.
    """
    logger.info("BMS scraper: fetching verified treasury data...")

    treasuries = _scrape_treasury_page(BMS_TREASURIES_URL)
    time.sleep(2)
    miners = _scrape_treasury_page(BMS_MINERS_URL)

    all_bms = treasuries + miners
    if not all_bms:
        logger.warning("BMS scraper: no data scraped")
        return {'updated': 0, 'validated': 0, 'new': 0}

    # Dedup by ticker
    seen = set()
    unique_bms = []
    for e in all_bms:
        key = e.get('ticker', '') or e.get('company', '')
        if key and key not in seen:
            seen.add(key)
            unique_bms.append(e)

    logger.info(f"  BMS: {len(unique_bms)} unique entities after dedup")

    try:
        result = supabase.table("treasury_companies").select(
            "id, company, ticker, btc_holdings, data_source, entity_type"
        ).eq("entity_type", "public_company").execute()
        db_entities = result.data or []
    except Exception as e:
        logger.debug(f"  BMS: DB fetch error: {e}")
        return {'updated': 0, 'validated': 0, 'new': 0}

    updated = 0
    validated = 0
    new_entities = 0

    for bms in unique_bms:
        match = _match_entity(bms, db_entities)

        if match:
            current_source = match.get('data_source', 'aggregator')
            current_btc = match.get('btc_holdings', 0) or 0
            bms_btc = bms['btc_holdings']

            # SAFETY CHECK: reject if >3x or <0.3x current value
            if current_btc > 0:
                ratio = bms_btc / current_btc
                if ratio > 3.0 or ratio < 0.3:
                    logger.debug(f"  BMS: REJECTED {match['company']} — {current_btc:,} → {bms_btc:,} BTC (ratio {ratio:.1f}x too extreme)")
                    continue

            current_priority = SOURCE_PRIORITY.get(current_source, 10)
            bms_priority = SOURCE_PRIORITY.get('bms_verified', 70)

            if bms_btc == current_btc:
                validated += 1
            elif bms_priority > current_priority:
                try:
                    supabase.table("treasury_companies").update({
                        'btc_holdings': bms_btc,
                        'data_source': 'bms_verified',
                        'source_updated_at': datetime.now().isoformat(),
                    }).eq("id", match["id"]).execute()
                    logger.info(f"  BMS: {match['company']} — {current_btc:,} → {bms_btc:,} BTC [bms_verified > {current_source}]")
                    updated += 1
                except Exception as e:
                    logger.debug(f"  BMS update error: {e}")
            else:
                validated += 1
        else:
            # Only add new entities with ticker and reasonable BTC
            if bms['btc_holdings'] >= 10 and bms.get('ticker'):
                try:
                    supabase.table("treasury_companies").insert({
                        'company': bms['company'][:200],
                        'ticker': bms['ticker'][:20],
                        'btc_holdings': bms['btc_holdings'],
                        'entity_type': 'public_company',
                        'is_government': False,
                        'data_source': 'bms_verified',
                        'source_updated_at': datetime.now().isoformat(),
                    }).execute()
                    logger.info(f"  BMS: NEW — {bms['company']} ({bms['ticker']}) — {bms['btc_holdings']:,} BTC")
                    new_entities += 1
                except Exception as e:
                    logger.debug(f"  BMS insert error: {e}")

    logger.info(f"BMS scraper: {updated} updated, {validated} validated, {new_entities} new entities")
    return {'updated': updated, 'validated': validated, 'new': new_entities}


if __name__ == "__main__":
    logger.info("BMS scraper — manual run...")
    result = sync_bms_data()
    print(f"Updated: {result['updated']}, Validated: {result['validated']}, New: {result['new']}")
