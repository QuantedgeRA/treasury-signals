"""
edgar_realtime.py — SEC EDGAR Real-Time 8-K Filing Monitor
------------------------------------------------------------
Monitors SEC EDGAR for new 8-K filings mentioning Bitcoin, BTC,
or digital assets. Catches corporate BTC purchases/sales within
minutes of filing.

Primary source: https://efts.sec.gov/LATEST/search-index
No API key required. Rate limit: 10 req/sec.

Usage:
    from edgar_realtime import check_edgar_filings
    check_edgar_filings()  # Call every 15 minutes
"""

import os
import re
import json
import time
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
from supabase import create_client
from logger import get_logger

logger = get_logger(__name__)
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_PAID_CHANNEL_ID = os.getenv("TELEGRAM_PAID_CHANNEL_ID")

# EDGAR full-text search API
EDGAR_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
EDGAR_FILING_URL = "https://www.sec.gov/Archives/edgar/data"

# Search terms that indicate BTC treasury activity
SEARCH_TERMS = [
    '"bitcoin"',
    '"btc"',
    '"digital asset" AND "treasury"',
    '"bitcoin treasury"',
    '"cryptocurrency" AND "purchase"',
]

# Keywords in filings that indicate a purchase/sale
PURCHASE_KEYWORDS = [
    'acquired', 'purchased', 'bought', 'acquisition of bitcoin',
    'purchase of bitcoin', 'acquired approximately', 'purchased approximately',
    'added to its bitcoin', 'increased its bitcoin', 'bitcoin holdings',
    'treasury reserve', 'digital asset reserve',
]

SALE_KEYWORDS = [
    'sold', 'disposed', 'liquidated', 'sale of bitcoin',
    'reduced its bitcoin', 'divested',
]

# BTC amount patterns in filings
BTC_PATTERNS = [
    r'(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*(?:BTC|bitcoin|bitcoins)',
    r'approximately\s+(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*(?:BTC|bitcoin)',
    r'(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*(?:BTC|bitcoin)\s*(?:for|at|worth)',
    r'acquired\s+(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*(?:BTC|bitcoin)',
    r'purchased\s+(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*(?:BTC|bitcoin)',
    r'holds?\s+(?:approximately\s+)?(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*(?:BTC|bitcoin)',
]

# USD amount patterns
USD_PATTERNS = [
    r'\$(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*(?:million|billion|M|B)',
    r'(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*(?:million|billion)\s*(?:dollars|\$|USD)',
]

HEADERS = {
    'User-Agent': 'TreasurySignalIntelligence admin@quantedgeriskadvisory.com',
    'Accept': 'application/json',
}

def _bridge_to_confirmed_purchases(filing_data):
    """
    Write EDGAR-detected purchases directly to confirmed_purchases
    so the dashboard shows them immediately (fast path via SEC, not BitcoinTreasuries.net).
    """
    if filing_data.get("event_type") not in ("purchase", "acquisition"):
        return

    btc_amount = filing_data.get("btc_amount", 0)
    if btc_amount <= 0:
        return

    usd_amount = filing_data.get("usd_amount", 0)
    price_per_btc = round(usd_amount / btc_amount) if btc_amount > 0 else 0

    purchase_id = f"edgar_{filing_data.get('ticker_cik', 'UNK')}_{filing_data.get('filing_date', '')}"

    try:
        supabase.table("confirmed_purchases").upsert({
            "purchase_id": purchase_id,
            "company": filing_data.get("company_name", ""),
            "ticker": filing_data.get("ticker_cik", ""),
            "btc_amount": btc_amount,
            "usd_amount": usd_amount,
            "price_per_btc": price_per_btc,
            "filing_date": filing_data.get("filing_date", ""),
            "filing_url": filing_data.get("filing_url", ""),
            "was_predicted": False,
            "source": "SEC EDGAR 8-K (real-time)",
        }, on_conflict="purchase_id").execute()
        logger.info(f"  ✅ Bridged to confirmed_purchases: {filing_data.get('company_name')} +{btc_amount:,.0f} BTC")
    except Exception as e:
        logger.debug(f"  ⚠️ Bridge to confirmed_purchases failed: {e}")


def _search_edgar(query, days_back=1):
    """Search EDGAR full-text search for recent filings."""
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')

    try:
        params = {
            'q': query,
            'dateRange': 'custom',
            'startdt': start_date,
            'enddt': end_date,
            'forms': '8-K,8-K/A',
        }
        resp = requests.get(EDGAR_SEARCH_URL, params=params, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return data.get('hits', {}).get('hits', [])
    except Exception as e:
        logger.debug(f"  EDGAR search error for '{query}': {e}")
        return []


def _fetch_filing_text(filing_url):
    """Fetch the text content of a filing."""
    try:
        time.sleep(0.5)  # Rate limit
        resp = requests.get(filing_url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        # Strip HTML tags for text analysis
        text = re.sub(r'<[^>]+>', ' ', resp.text)
        text = re.sub(r'\s+', ' ', text)
        return text[:50000]  # First 50K chars
    except Exception as e:
        logger.debug(f"  EDGAR fetch error: {e}")
        return ""


def _extract_btc_amount(text):
    """Extract BTC amount from filing text."""
    text_lower = text.lower()
    for pattern in BTC_PATTERNS:
        matches = re.findall(pattern, text_lower)
        if matches:
            # Return the largest BTC amount found
            amounts = []
            for m in matches:
                clean = m.replace(',', '')
                try:
                    amounts.append(float(clean))
                except:
                    pass
            if amounts:
                return max(amounts)
    return 0


def _extract_usd_amount(text):
    """Extract USD amount from filing text."""
    text_lower = text.lower()
    for pattern in USD_PATTERNS:
        matches = re.findall(pattern, text_lower)
        if matches:
            amounts = []
            for m in matches:
                clean = m.replace(',', '')
                try:
                    val = float(clean)
                    # Check if million/billion multiplier follows
                    if 'billion' in text_lower or 'B' in text:
                        val *= 1_000_000_000
                    elif 'million' in text_lower or 'M' in text:
                        val *= 1_000_000
                    amounts.append(val)
                except:
                    pass
            if amounts:
                return max(amounts)
    return 0


def _classify_event(text):
    """Classify whether the filing describes a purchase, sale, or holding."""
    text_lower = text.lower()
    purchase_score = sum(1 for kw in PURCHASE_KEYWORDS if kw in text_lower)
    sale_score = sum(1 for kw in SALE_KEYWORDS if kw in text_lower)

    if purchase_score > sale_score:
        return 'purchase'
    elif sale_score > purchase_score:
        return 'sale'
    return 'holding'


def _get_processed_filings():
    """Get list of already-processed filing accession numbers."""
    try:
        result = supabase.table("edgar_filings").select("accession_number").execute()
        return set(r['accession_number'] for r in (result.data or []))
    except:
        return set()


def _store_filing(filing_data):
    """Store a processed filing in the database."""
    try:
        supabase.table("edgar_filings").upsert(filing_data, on_conflict="accession_number").execute()
    except Exception as e:
        logger.debug(f"  EDGAR store error: {e}")


def _send_alert(company, ticker, event_type, btc_amount, usd_amount, filing_url):
    """Send Telegram alert for detected BTC activity."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_PAID_CHANNEL_ID:
        return

    emoji = '🟢' if event_type == 'purchase' else '🔴' if event_type == 'sale' else '📋'
    action = 'PURCHASED' if event_type == 'purchase' else 'SOLD' if event_type == 'sale' else 'REPORTED HOLDING'

    msg = f"{emoji} **SEC FILING DETECTED**\n\n"
    msg += f"**{company}** ({ticker}) {action}\n"
    if btc_amount > 0:
        msg += f"₿ {btc_amount:,.0f} BTC\n"
    if usd_amount > 0:
        msg += f"💵 ${usd_amount:,.0f}\n"
    msg += f"\n📄 [View Filing]({filing_url})\n"
    msg += f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}"

    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                'chat_id': TELEGRAM_PAID_CHANNEL_ID,
                'text': msg,
                'parse_mode': 'Markdown',
                'disable_web_page_preview': True,
            },
            timeout=10,
        )
        logger.info(f"  EDGAR alert sent: {company} {event_type} {btc_amount} BTC")
    except Exception as e:
        logger.debug(f"  EDGAR alert error: {e}")


def check_edgar_filings(days_back=1):
    """
    Main function: Search EDGAR for new Bitcoin-related 8-K filings.
    Call every 15 minutes for near-real-time detection.
    """
    logger.info("EDGAR monitor: checking for new filings...")

    processed = _get_processed_filings()
    new_filings = 0
    alerts_sent = 0

    for query in SEARCH_TERMS:
        hits = _search_edgar(query, days_back)
        if not hits:
            continue

        for hit in hits:
            source = hit.get('_source', {})
            accession = source.get('file_num', '') or source.get('accession_no', '')
            if not accession:
                continue

            # Skip already processed
            if accession in processed:
                continue

            company_name = source.get('display_names', [''])[0] if source.get('display_names') else source.get('entity_name', '')
            ticker_cik = source.get('entity_name', '')
            filing_date = source.get('file_date', '')
            form_type = source.get('form_type', '8-K')

            # Get filing URL
            filing_url = ''
            if source.get('file_num'):
                filing_url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&filenum={source['file_num']}&type=8-K&dateb=&owner=include&count=10"

            # Fetch and analyze filing text
            primary_doc = source.get('file_url', '')
            if primary_doc:
                text = _fetch_filing_text(f"https://efts.sec.gov{primary_doc}")
            else:
                text = source.get('text', '')

            if not text:
                continue

            # Check if this filing mentions Bitcoin in a treasury context
            text_lower = text.lower()
            if not any(term in text_lower for term in ['bitcoin', 'btc', 'digital asset treasury', 'cryptocurrency reserve']):
                continue

            # Extract data
            btc_amount = _extract_btc_amount(text)
            usd_amount = _extract_usd_amount(text)
            event_type = _classify_event(text)

            # Store filing
            filing_data = {
                'accession_number': accession,
                'company_name': company_name[:200],
                'ticker_cik': ticker_cik[:50],
                'filing_date': filing_date or datetime.now().strftime('%Y-%m-%d'),
                'form_type': form_type,
                'event_type': event_type,
                'btc_amount': btc_amount,
                'usd_amount': usd_amount,
                'filing_url': filing_url[:500],
                'processed_at': datetime.now().isoformat(),
            }
            _store_filing(filing_data)
            _bridge_to_confirmed_purchases(filing_data)
            processed.add(accession)
            new_filings += 1

            # Send alert for purchases and sales
            if event_type in ('purchase', 'sale') and (btc_amount > 0 or usd_amount > 0):
                _send_alert(company_name, ticker_cik, event_type, btc_amount, usd_amount, filing_url)
                alerts_sent += 1

            logger.info(f"  EDGAR: {company_name} — {event_type} — {btc_amount:,.0f} BTC — {filing_date}")

        time.sleep(1)  # Rate limit between queries

    logger.info(f"EDGAR monitor: {new_filings} new filings, {alerts_sent} alerts sent")
    return {'new_filings': new_filings, 'alerts_sent': alerts_sent}


if __name__ == "__main__":
    logger.info("EDGAR monitor — manual run (last 3 days)...")
    result = check_edgar_filings(days_back=3)
    print(f"New filings: {result['new_filings']}, Alerts: {result['alerts_sent']}")
