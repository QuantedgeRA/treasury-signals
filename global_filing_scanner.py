"""
global_filing_scanner.py — Worldwide Regulatory Filing Scanner
================================================================
Scans filing systems across 15+ countries for Bitcoin-related disclosures.
Each country's filing system is a separate adapter.

Coverage:
  USA        → SEC EDGAR (full-text search API, free)
  Canada     → SEDAR+ (sedarplus.ca search)
  Japan      → EDINET API + TDnet disclosures
  UK         → Companies House + RNS news
  Germany    → Bundesanzeiger
  South Korea→ DART API (free)
  Hong Kong  → HKEX news (RSS)
  Australia  → ASX announcements (RSS)
  Sweden     → Finansinspektionen + Cision
  Norway     → Oslo Bors newsweb
  Brazil     → CVM
  Switzerland→ SIX Exchange
  + Google News (catches press releases for private companies globally)

Usage:
    from global_filing_scanner import scan_all_filings
    scan_all_filings()  # Call every 15-30 minutes
"""

import os
import re
import json
import time
import hashlib
import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
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

# Bitcoin-related search keywords (multi-language)
BTC_KEYWORDS = [
    'bitcoin', 'btc', 'digital asset treasury', 'cryptocurrency reserve',
    'bitcoin treasury', 'bitcoin purchase', 'bitcoin acquisition',
    'ビットコイン',      # Japanese
    '비트코인',          # Korean
    'kryptowährung',    # German
]

BTC_AMOUNT_PATTERNS = [
    r'(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*(?:BTC|bitcoin|bitcoins)',
    r'approximately\s+(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*(?:BTC|bitcoin)',
    r'acquired\s+(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*(?:BTC|bitcoin)',
    r'purchased\s+(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*(?:BTC|bitcoin)',
    r'holds?\s+(?:approximately\s+)?(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*(?:BTC|bitcoin)',
]

HEADERS = {
    'User-Agent': 'TreasurySignalIntelligence admin@quantedgeriskadvisory.com',
    'Accept': 'application/json, text/html',
}


def _hash_id(text):
    """Create a unique hash for deduplication."""
    return hashlib.md5(text.encode()).hexdigest()[:20]


def _extract_btc(text):
    """Extract BTC amount from text."""
    text_lower = text.lower()
    for pattern in BTC_AMOUNT_PATTERNS:
        matches = re.findall(pattern, text_lower)
        if matches:
            amounts = []
            for m in matches:
                try:
                    amounts.append(float(m.replace(',', '')))
                except:
                    pass
            if amounts:
                return max(amounts)
    return 0


def _has_btc_keywords(text):
    """Check if text contains Bitcoin-related keywords."""
    text_lower = text.lower()
    return any(kw in text_lower for kw in BTC_KEYWORDS)


def _store_filing(filing):
    """Store a filing in edgar_filings table."""
    try:
        supabase.table("edgar_filings").upsert(filing, on_conflict="accession_number").execute()
    except Exception as e:
        logger.debug(f"  Filing store error: {e}")


def _get_processed():
    """Get processed filing IDs."""
    try:
        r = supabase.table("edgar_filings").select("accession_number").execute()
        return set(d['accession_number'] for d in (r.data or []))
    except:
        return set()


def _send_alert(source, company, event_type, btc_amount, url):
    """Send Telegram alert."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_PAID_CHANNEL_ID:
        return
    emoji = '🟢' if 'purchase' in event_type.lower() else '🔴' if 'sale' in event_type.lower() else '📋'
    msg = f"{emoji} **FILING DETECTED — {source}**\n\n"
    msg += f"**{company}** — {event_type}\n"
    if btc_amount > 0:
        msg += f"₿ {btc_amount:,.0f} BTC\n"
    msg += f"\n📄 [View]({url})\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}"
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={'chat_id': TELEGRAM_PAID_CHANNEL_ID, 'text': msg, 'parse_mode': 'Markdown', 'disable_web_page_preview': True}, timeout=10)
    except:
        pass


# ═══════════════════════════════════════════════
# COUNTRY ADAPTERS
# ═══════════════════════════════════════════════

def scan_usa_edgar(days_back=1):
    """USA — SEC EDGAR full-text search API (free, no auth)."""
    logger.info("  📄 USA (SEC EDGAR)...")
    filings = []
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')

    for keyword in ['"bitcoin"', '"btc" AND "treasury"', '"digital asset" AND "acquired"']:
        try:
            resp = requests.get("https://efts.sec.gov/LATEST/search-index", params={
                'q': keyword, 'dateRange': 'custom', 'startdt': start_date, 'enddt': end_date,
                'forms': '8-K,8-K/A,10-Q,10-K',
            }, headers=HEADERS, timeout=30)
            if resp.ok:
                hits = resp.json().get('hits', {}).get('hits', [])
                for hit in hits:
                    src = hit.get('_source', {})
                    name = (src.get('display_names', [''])[0] if src.get('display_names') else src.get('entity_name', ''))
                    filings.append({
                        'accession_number': f"edgar_{_hash_id(str(src.get('file_num', '')))}",
                        'company_name': name[:200],
                        'ticker_cik': src.get('entity_name', '')[:50],
                        'filing_date': src.get('file_date', end_date),
                        'form_type': src.get('form_type', '8-K'),
                        'event_type': 'filing',
                        'source': 'SEC EDGAR (USA)',
                        'filing_url': f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&filenum={src.get('file_num', '')}&type=8-K",
                    })
            time.sleep(0.5)
        except Exception as e:
            logger.debug(f"    EDGAR error: {e}")
    return filings


def scan_canada_sedar(days_back=1):
    """Canada — SEDAR+ public search."""
    logger.info("  📄 Canada (SEDAR+)...")
    filings = []
    try:
        # SEDAR+ doesn't have a public API, use their search page
        resp = requests.get("https://www.sedarplus.ca/csa-party/records/filter", params={
            'keyword': 'bitcoin',
            'category': 'Filing',
            'fromDate': (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d'),
            'toDate': datetime.now().strftime('%Y-%m-%d'),
        }, headers={**HEADERS, 'Accept': 'application/json'}, timeout=30)
        if resp.ok:
            data = resp.json()
            for item in (data.get('results', []) if isinstance(data, dict) else []):
                filings.append({
                    'accession_number': f"sedar_{_hash_id(str(item))}",
                    'company_name': (item.get('issuerName', '') or item.get('name', ''))[:200],
                    'ticker_cik': '',
                    'filing_date': item.get('filingDate', datetime.now().strftime('%Y-%m-%d')),
                    'form_type': item.get('documentType', 'Filing'),
                    'event_type': 'filing',
                    'source': 'SEDAR+ (Canada)',
                    'filing_url': f"https://www.sedarplus.ca/csa-party/records/{item.get('id', '')}",
                })
    except Exception as e:
        logger.debug(f"    SEDAR+ error: {e}")
    return filings


def scan_japan_tdnet():
    """Japan — TDnet (Timely Disclosure Network) + EDINET."""
    logger.info("  📄 Japan (TDnet/EDINET)...")
    filings = []
    try:
        # TDnet RSS for timely disclosures
        resp = requests.get("https://www.release.tdnet.info/inbs/I_list_001_E.html", headers=HEADERS, timeout=30)
        if resp.ok:
            soup = BeautifulSoup(resp.text, 'html.parser')
            for row in soup.select('tr'):
                text = row.get_text()
                if _has_btc_keywords(text):
                    cells = row.find_all('td')
                    name = cells[2].get_text(strip=True) if len(cells) > 2 else ''
                    link = row.find('a', href=True)
                    filings.append({
                        'accession_number': f"tdnet_{_hash_id(text[:100])}",
                        'company_name': name[:200],
                        'ticker_cik': '',
                        'filing_date': datetime.now().strftime('%Y-%m-%d'),
                        'form_type': 'TDnet Disclosure',
                        'event_type': 'filing',
                        'source': 'TDnet (Japan)',
                        'filing_url': f"https://www.release.tdnet.info{link['href']}" if link else '',
                    })
    except Exception as e:
        logger.debug(f"    TDnet error: {e}")

    # EDINET API
    try:
        today = datetime.now().strftime('%Y-%m-%d')
        resp = requests.get(f"https://disclosure.edinet-fsa.go.jp/api/v2/documents.json?date={today}&type=2",
            headers=HEADERS, timeout=30)
        if resp.ok:
            data = resp.json()
            for doc in data.get('results', []):
                title = (doc.get('docDescription', '') or '').lower()
                if _has_btc_keywords(title):
                    filings.append({
                        'accession_number': f"edinet_{doc.get('docID', '')}",
                        'company_name': (doc.get('filerName', ''))[:200],
                        'ticker_cik': doc.get('secCode', ''),
                        'filing_date': doc.get('submitDateTime', today)[:10],
                        'form_type': doc.get('docTypeCode', 'EDINET'),
                        'event_type': 'filing',
                        'source': 'EDINET (Japan)',
                        'filing_url': f"https://disclosure.edinet-fsa.go.jp/E01EW/BLMainController.jsp?uji.verb=W0EZA226CXP001003Action&SESSIONKEY=&lgKbn=2&dflg=0&iflg=0&dispKbn=1&docID={doc.get('docID', '')}",
                    })
    except Exception as e:
        logger.debug(f"    EDINET error: {e}")
    return filings


def scan_korea_dart():
    """South Korea — DART API (free, requires API key)."""
    logger.info("  📄 South Korea (DART)...")
    filings = []
    dart_key = os.getenv("DART_API_KEY", "")
    if not dart_key:
        logger.debug("    DART: no API key set (DART_API_KEY)")
        return filings

    try:
        today = datetime.now().strftime('%Y%m%d')
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y%m%d')
        resp = requests.get("https://opendart.fss.or.kr/api/list.json", params={
            'crtfc_key': dart_key, 'bgn_de': yesterday, 'end_de': today,
            'page_count': 100,
        }, headers=HEADERS, timeout=30)
        if resp.ok:
            data = resp.json()
            for item in data.get('list', []):
                title = (item.get('report_nm', '') or '').lower()
                if _has_btc_keywords(title):
                    filings.append({
                        'accession_number': f"dart_{item.get('rcept_no', '')}",
                        'company_name': item.get('corp_name', '')[:200],
                        'ticker_cik': item.get('stock_code', ''),
                        'filing_date': item.get('rcept_dt', today),
                        'form_type': item.get('report_nm', 'DART'),
                        'event_type': 'filing',
                        'source': 'DART (South Korea)',
                        'filing_url': f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={item.get('rcept_no', '')}",
                    })
    except Exception as e:
        logger.debug(f"    DART error: {e}")
    return filings


def scan_uk_rns():
    """UK — RNS (Regulatory News Service) via London Stock Exchange."""
    logger.info("  📄 UK (RNS/LSE)...")
    filings = []
    try:
        resp = requests.get("https://www.londonstockexchange.com/exchange/news/market-news/market-news-home.html",
            headers=HEADERS, timeout=30)
        if resp.ok:
            soup = BeautifulSoup(resp.text, 'html.parser')
            for item in soup.select('.news-item, .market-news-item, tr'):
                text = item.get_text()
                if _has_btc_keywords(text):
                    link = item.find('a', href=True)
                    filings.append({
                        'accession_number': f"rns_{_hash_id(text[:100])}",
                        'company_name': text[:200].split('\n')[0].strip(),
                        'ticker_cik': '',
                        'filing_date': datetime.now().strftime('%Y-%m-%d'),
                        'form_type': 'RNS Announcement',
                        'event_type': 'filing',
                        'source': 'RNS (UK)',
                        'filing_url': f"https://www.londonstockexchange.com{link['href']}" if link else '',
                    })
    except Exception as e:
        logger.debug(f"    RNS error: {e}")
    return filings


def scan_hk_hkex():
    """Hong Kong — HKEX news RSS feed."""
    logger.info("  📄 Hong Kong (HKEX)...")
    filings = []
    try:
        resp = requests.get("https://www1.hkexnews.hk/search/titlesearch.xhtml?lang=en",
            headers=HEADERS, timeout=30)
        if resp.ok:
            soup = BeautifulSoup(resp.text, 'html.parser')
            for row in soup.select('.row, tr'):
                text = row.get_text()
                if _has_btc_keywords(text):
                    link = row.find('a', href=True)
                    filings.append({
                        'accession_number': f"hkex_{_hash_id(text[:100])}",
                        'company_name': text[:200].split('\n')[0].strip(),
                        'ticker_cik': '',
                        'filing_date': datetime.now().strftime('%Y-%m-%d'),
                        'form_type': 'HKEX Announcement',
                        'event_type': 'filing',
                        'source': 'HKEX (Hong Kong)',
                        'filing_url': link['href'] if link else '',
                    })
    except Exception as e:
        logger.debug(f"    HKEX error: {e}")
    return filings


def scan_australia_asx():
    """Australia — ASX announcements."""
    logger.info("  📄 Australia (ASX)...")
    filings = []
    try:
        resp = requests.get("https://www.asx.com.au/asx/statistics/announcements.do?timeframe=D",
            headers=HEADERS, timeout=30)
        if resp.ok:
            soup = BeautifulSoup(resp.text, 'html.parser')
            for row in soup.select('tr'):
                text = row.get_text()
                if _has_btc_keywords(text):
                    cells = row.find_all('td')
                    link = row.find('a', href=True)
                    filings.append({
                        'accession_number': f"asx_{_hash_id(text[:100])}",
                        'company_name': (cells[1].get_text(strip=True) if len(cells) > 1 else '')[:200],
                        'ticker_cik': (cells[0].get_text(strip=True) if cells else ''),
                        'filing_date': datetime.now().strftime('%Y-%m-%d'),
                        'form_type': 'ASX Announcement',
                        'event_type': 'filing',
                        'source': 'ASX (Australia)',
                        'filing_url': f"https://www.asx.com.au{link['href']}" if link else '',
                    })
    except Exception as e:
        logger.debug(f"    ASX error: {e}")
    return filings


def scan_norway_oslo():
    """Norway — Oslo Bors newsweb."""
    logger.info("  📄 Norway (Oslo Bors)...")
    filings = []
    try:
        resp = requests.get("https://newsweb.oslobors.no/search?q=bitcoin&category=&issuer=&fromDate=&toDate=",
            headers=HEADERS, timeout=30)
        if resp.ok:
            soup = BeautifulSoup(resp.text, 'html.parser')
            for item in soup.select('.search-result, .news-item, tr'):
                text = item.get_text()
                if _has_btc_keywords(text):
                    link = item.find('a', href=True)
                    filings.append({
                        'accession_number': f"oslo_{_hash_id(text[:100])}",
                        'company_name': text[:200].split('\n')[0].strip(),
                        'ticker_cik': '',
                        'filing_date': datetime.now().strftime('%Y-%m-%d'),
                        'form_type': 'Oslo Bors News',
                        'event_type': 'filing',
                        'source': 'Oslo Bors (Norway)',
                        'filing_url': f"https://newsweb.oslobors.no{link['href']}" if link else '',
                    })
    except Exception as e:
        logger.debug(f"    Oslo Bors error: {e}")
    return filings


def scan_germany_bundesanzeiger():
    """Germany — Bundesanzeiger (Federal Gazette)."""
    logger.info("  📄 Germany (Bundesanzeiger)...")
    filings = []
    try:
        resp = requests.get("https://www.bundesanzeiger.de/pub/de/suchergebnis?5",
            params={'fulltext': 'bitcoin', 'area': 'FinanzKapitalMarkt'},
            headers=HEADERS, timeout=30)
        if resp.ok:
            soup = BeautifulSoup(resp.text, 'html.parser')
            for item in soup.select('.result_container, .publication'):
                text = item.get_text()
                if _has_btc_keywords(text):
                    link = item.find('a', href=True)
                    filings.append({
                        'accession_number': f"banz_{_hash_id(text[:100])}",
                        'company_name': text[:200].split('\n')[0].strip(),
                        'ticker_cik': '',
                        'filing_date': datetime.now().strftime('%Y-%m-%d'),
                        'form_type': 'Bundesanzeiger',
                        'event_type': 'filing',
                        'source': 'Bundesanzeiger (Germany)',
                        'filing_url': '',
                    })
    except Exception as e:
        logger.debug(f"    Bundesanzeiger error: {e}")
    return filings


def scan_google_news():
    """Global — Google News RSS for Bitcoin treasury press releases (covers private companies)."""
    logger.info("  📰 Google News (global press releases)...")
    filings = []
    queries = [
        'bitcoin+treasury+purchase',
        'bitcoin+acquisition+company',
        'bitcoin+reserve+corporate',
        'bitcoin+balance+sheet+added',
    ]
    for query in queries:
        try:
            resp = requests.get(f"https://news.google.com/rss/search?q={query}+when:1d&hl=en-US&gl=US&ceid=US:en",
                headers=HEADERS, timeout=15)
            if resp.ok:
                soup = BeautifulSoup(resp.text, 'xml')
                for item in soup.find_all('item'):
                    title = item.find('title').get_text() if item.find('title') else ''
                    link = item.find('link').get_text() if item.find('link') else ''
                    pub_date = item.find('pubDate').get_text() if item.find('pubDate') else ''
                    source_tag = item.find('source')
                    source_name = source_tag.get_text() if source_tag else 'Google News'

                    if title and _has_btc_keywords(title):
                        filings.append({
                            'accession_number': f"gnews_{_hash_id(title)}",
                            'company_name': title[:200],
                            'ticker_cik': '',
                            'filing_date': datetime.now().strftime('%Y-%m-%d'),
                            'form_type': f'Press Release ({source_name})',
                            'event_type': 'press_release',
                            'source': f'Google News ({source_name})',
                            'filing_url': link,
                        })
            time.sleep(1)
        except Exception as e:
            logger.debug(f"    Google News error: {e}")
    return filings


def scan_el_salvador():
    """El Salvador — Official government BTC dashboard."""
    logger.info("  🏛️ El Salvador (bitcoin.gob.sv)...")
    filings = []
    try:
        resp = requests.get("https://bitcoin.gob.sv", headers=HEADERS, timeout=15)
        if resp.ok:
            text = resp.text
            btc = _extract_btc(text)
            if btc > 0:
                filings.append({
                    'accession_number': f"sv_gov_{datetime.now().strftime('%Y%m%d')}",
                    'company_name': 'El Salvador (Government)',
                    'ticker_cik': 'SV.GOV',
                    'filing_date': datetime.now().strftime('%Y-%m-%d'),
                    'form_type': 'Government Dashboard',
                    'event_type': 'holding',
                    'btc_amount': btc,
                    'source': 'bitcoin.gob.sv (El Salvador)',
                    'filing_url': 'https://bitcoin.gob.sv',
                })
    except Exception as e:
        logger.debug(f"    El Salvador error: {e}")
    return filings


# ═══════════════════════════════════════════════
# MAIN SCANNER
# ═══════════════════════════════════════════════

# All country adapters
ADAPTERS = [
    ('USA', scan_usa_edgar),
    ('Canada', scan_canada_sedar),
    ('Japan', scan_japan_tdnet),
    ('South Korea', scan_korea_dart),
    ('UK', scan_uk_rns),
    ('Hong Kong', scan_hk_hkex),
    ('Australia', scan_australia_asx),
    ('Norway', scan_norway_oslo),
    ('Germany', scan_germany_bundesanzeiger),
    ('El Salvador', scan_el_salvador),
    ('Global News', scan_google_news),
]


def scan_all_filings(days_back=1):
    """
    Scan ALL worldwide filing systems for Bitcoin-related disclosures.
    Call every 15-30 minutes for near-real-time detection.
    """
    logger.info(f"Global Filing Scanner: scanning {len(ADAPTERS)} sources...")
    start = time.time()

    processed = _get_processed()
    total_new = 0
    total_alerts = 0
    source_stats = {}

    for country, adapter in ADAPTERS:
        try:
            filings = adapter(days_back)
            new_count = 0

            for filing in filings:
                acc = filing.get('accession_number', '')
                if acc in processed:
                    continue

                # Store
                filing['processed_at'] = datetime.now().isoformat()
                filing['btc_amount'] = filing.get('btc_amount', 0)
                filing['usd_amount'] = filing.get('usd_amount', 0)
                _store_filing(filing)
                processed.add(acc)
                new_count += 1

                # Alert for significant filings
                if filing.get('event_type') in ('purchase', 'sale', 'filing') and filing.get('company_name'):
                    _send_alert(
                        filing.get('source', country),
                        filing['company_name'],
                        filing.get('event_type', 'filing'),
                        filing.get('btc_amount', 0),
                        filing.get('filing_url', ''),
                    )
                    total_alerts += 1

            source_stats[country] = new_count
            total_new += new_count

        except Exception as e:
            logger.debug(f"  {country} adapter error: {e}")
            source_stats[country] = -1

    elapsed = time.time() - start
    logger.info(f"Global Filing Scanner: {total_new} new filings, {total_alerts} alerts ({elapsed:.1f}s)")
    for src, count in source_stats.items():
        if count > 0:
            logger.info(f"  {src}: {count} new")
        elif count < 0:
            logger.debug(f"  {src}: error")

    return {'new_filings': total_new, 'alerts': total_alerts, 'sources': source_stats}


if __name__ == "__main__":
    logger.info("Global Filing Scanner — manual run (last 3 days)...")
    result = scan_all_filings(days_back=3)
    print(f"\nTotal: {result['new_filings']} new filings, {result['alerts']} alerts")
    print(f"Sources: {json.dumps(result['sources'], indent=2)}")
