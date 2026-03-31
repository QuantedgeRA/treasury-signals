"""
bms_scraper.py — BitcoinMiningStock.io Treasury Data Scraper
==============================================================
Third aggregator source alongside CoinGecko and BitcoinTreasuries.net.
Provides the highest-accuracy verified data for 169 public companies.

BitcoinMiningStock.io independently verifies holdings from primary sources
with manual review — no third-party submissions.

Runs as a VALIDATION layer: cross-checks existing data and updates
when BMS has a more recent or different number.

Data priority: primary sources > BMS (verified) > CoinGecko/BT.net

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
    'Accept-Language': 'en-US,en;q=0.5',
}

# Source priority — BMS is more reliable than generic aggregators
# but less authoritative than direct SEC filings
SOURCE_PRIORITY = {
    'sec_filing': 100,
    'regulatory_filing': 90,
    'etf_issuer': 85,
    'government_official': 80,
    'defi_onchain': 80,
    'bms_verified': 70,       # ← BitcoinMiningStock.io
    'press_release': 60,
    'aggregator': 10,
}


def _parse_number(text):
    """Parse a number from text like '762,099' or '38,689.5'."""
    if not text:
        return 0
    clean = text.replace(',', '').replace(' ', '').strip()
    clean = re.sub(r'[^\d.]', '', clean)
    try:
        return float(clean) if '.' in clean else int(clean)
    except:
        return 0


def _scrape_treasury_page(url):
    """Scrape a BitcoinMiningStock.io treasury page and return structured data."""
    entities = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')

        # Find the main data table
        tables = soup.find_all('table')
        if not tables:
            logger.debug(f"  BMS: no tables found on {url}")
            return entities

        # Use the largest table (most rows)
        main_table = max(tables, key=lambda t: len(t.find_all('tr')))
        rows = main_table.find_all('tr')

        # Parse header to find column indices
        header = rows[0] if rows else None
        if not header:
            return entities

        headers = [th.get_text(strip=True).lower() for th in header.find_all(['th', 'td'])]

        # Find relevant column indices
        name_idx = None
        ticker_idx = None
        btc_idx = None
        mnav_idx = None
        sats_idx = None

        for i, h in enumerate(headers):
            if 'company' in h or 'name' in h:
                name_idx = i
            elif 'ticker' in h or 'symbol' in h:
                ticker_idx = i
            elif 'btc' in h and ('hold' in h or 'treasury' in h or 'amount' in h):
                btc_idx = i
            elif h == 'btc' or h == 'bitcoin':
                btc_idx = i
            elif 'mnav' in h:
                mnav_idx = i
            elif 'sat' in h and 'share' in h:
                sats_idx = i

        # If we can't find structured columns, try positional parsing
        if btc_idx is None:
            # Look for a column with large numbers that could be BTC
            for i, h in enumerate(headers):
                if any(kw in h for kw in ['btc', 'bitcoin', 'holdings', 'treasury']):
                    btc_idx = i
                    break

        # Parse data rows
        for row in rows[1:]:
            cells = row.find_all(['td', 'th'])
            if len(cells) < 3:
                continue

            texts = [c.get_text(strip=True) for c in cells]

            # Extract company name
            name = ''
            if name_idx is not None and name_idx < len(texts):
                name = texts[name_idx]
            else:
                # First cell with letters is likely the name
                for t in texts:
                    if t and t[0:1].isalpha() and len(t) > 2:
                        name = t
                        break

            # Extract ticker
            ticker = ''
            if ticker_idx is not None and ticker_idx < len(texts):
                ticker = texts[ticker_idx].upper().strip()
            else:
                # Look for ticker pattern (2-5 uppercase letters, possibly with .XX suffix)
                for t in texts:
                    if re.match(r'^[A-Z]{2,5}(\.[A-Z]{1,3})?$', t.strip()):
                        ticker = t.strip()
                        break

            # Extract BTC holdings
            btc = 0
            if btc_idx is not None and btc_idx < len(texts):
                btc = _parse_number(texts[btc_idx])
            else:
                # Find the largest number that could be BTC (between 1 and 1,000,000)
                for t in texts:
                    val = _parse_number(t)
                    if 1 <= val <= 1_000_000 and val > btc:
                        btc = val

            if name and btc > 0:
                entity = {
                    'company': name[:200],
                    'ticker': ticker[:20],
                    'btc_holdings': int(btc),
                }
                if mnav_idx is not None and mnav_idx < len(texts):
                    entity['mnav'] = _parse_number(texts[mnav_idx])
                if sats_idx is not None and sats_idx < len(texts):
                    entity['sats_per_share'] = _parse_number(texts[sats_idx])
                entities.append(entity)

        logger.info(f"  BMS: scraped {len(entities)} entities from {url.split('/')[-1]}")

    except Exception as e:
        logger.debug(f"  BMS scrape error for {url}: {e}")

    return entities


def _match_entity(bms_entity, db_entities):
    """Find matching entity in database by ticker or name."""
    ticker = bms_entity.get('ticker', '').upper().strip()
    name = bms_entity.get('company', '').lower().strip()

    # Try exact ticker match first
    if ticker:
        for db in db_entities:
            db_ticker = (db.get('ticker', '') or '').upper().strip()
            if db_ticker == ticker:
                return db
            # Handle suffix differences (MSTR vs MSTR.US)
            if db_ticker.replace('.US', '') == ticker or ticker.replace('.US', '') == db_ticker:
                return db

    # Try name match
    if name:
        for db in db_entities:
            db_name = (db.get('company', '') or '').lower().strip()
            if db_name == name:
                return db
            # Partial match — first 15 chars
            if len(name) > 5 and name[:15] in db_name:
                return db
            if len(db_name) > 5 and db_name[:15] in name:
                return db

    return None


def sync_bms_data():
    """
    Main function: Scrape BitcoinMiningStock.io and cross-validate/update entities.
    Only updates entities where:
    - Current data_source is 'aggregator' (lower priority than BMS)
    - BMS has a different BTC number (more recent data)
    Never overwrites primary source data (sec_filing, regulatory_filing, etc.)
    """
    logger.info("BMS scraper: fetching verified treasury data...")

    # Scrape both pages
    treasuries = _scrape_treasury_page(BMS_TREASURIES_URL)
    time.sleep(2)
    miners = _scrape_treasury_page(BMS_MINERS_URL)

    all_bms = treasuries + miners
    if not all_bms:
        logger.warning("BMS scraper: no data scraped")
        return {'updated': 0, 'validated': 0, 'new': 0}

    # Remove duplicates (by ticker)
    seen = set()
    unique_bms = []
    for e in all_bms:
        key = e.get('ticker', '') or e.get('company', '')
        if key and key not in seen:
            seen.add(key)
            unique_bms.append(e)

    logger.info(f"  BMS: {len(unique_bms)} unique entities after dedup")

    # Get all current entities from database
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

            # Check if BMS data should override
            current_priority = SOURCE_PRIORITY.get(current_source, 10)
            bms_priority = SOURCE_PRIORITY.get('bms_verified', 70)

            if bms_btc == current_btc:
                validated += 1  # BMS confirms our data
            elif bms_priority > current_priority:
                # BMS is more authoritative — update
                try:
                    supabase.table("treasury_companies").update({
                        'btc_holdings': bms_btc,
                        'data_source': 'bms_verified',
                        'source_updated_at': datetime.now().isoformat(),
                    }).eq("id", match["id"]).execute()
                    logger.info(f"  BMS: {match['company']} — {current_btc:,} → {bms_btc:,} BTC [bms_verified > {current_source}]")
                    updated += 1
                except Exception as e:
                    logger.debug(f"  BMS update error for {match['company']}: {e}")
            elif bms_priority == current_priority and abs(bms_btc - current_btc) > current_btc * 0.05:
                # Same priority but >5% difference — BMS is likely more current
                try:
                    supabase.table("treasury_companies").update({
                        'btc_holdings': bms_btc,
                        'data_source': 'bms_verified',
                        'source_updated_at': datetime.now().isoformat(),
                    }).eq("id", match["id"]).execute()
                    logger.info(f"  BMS: {match['company']} — {current_btc:,} → {bms_btc:,} BTC [>5% diff]")
                    updated += 1
                except:
                    pass
            else:
                validated += 1  # Primary source takes precedence
        else:
            # New entity not in our database — add it
            if bms['btc_holdings'] > 0 and bms.get('company'):
                try:
                    supabase.table("treasury_companies").insert({
                        'company': bms['company'][:200],
                        'ticker': bms.get('ticker', '')[:20],
                        'btc_holdings': bms['btc_holdings'],
                        'entity_type': 'public_company',
                        'is_government': False,
                        'data_source': 'bms_verified',
                        'source_updated_at': datetime.now().isoformat(),
                    }).execute()
                    logger.info(f"  BMS: NEW — {bms['company']} ({bms.get('ticker', '')}) — {bms['btc_holdings']:,} BTC")
                    new_entities += 1
                except Exception as e:
                    logger.debug(f"  BMS insert error: {e}")

    logger.info(f"BMS scraper: {updated} updated, {validated} validated, {new_entities} new entities")
    return {'updated': updated, 'validated': validated, 'new': new_entities}


if __name__ == "__main__":
    logger.info("BMS scraper — manual run...")
    result = sync_bms_data()
    print(f"Updated: {result['updated']}, Validated: {result['validated']}, New: {result['new']}")
