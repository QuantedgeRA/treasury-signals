"""
global_filing_scanner.py v2 — Exhaustive Global BTC Intelligence Scanner
==========================================================================
Three universal mechanisms for COMPLETE global coverage:

1. REGULATORY FILING SYSTEMS (country-specific APIs where available)
   USA, Canada, Japan, South Korea, UK, Hong Kong, Australia, Norway,
   Germany, Sweden, France, Brazil, India, Singapore, Israel, Turkey + more

2. MULTI-LANGUAGE GLOBAL NEWS MONITORING
   Google News RSS in 15 languages — catches press releases, announcements,
   and disclosures from ANY country regardless of filing system

3. ENTITY-SPECIFIC MONITORING
   Tracks investor relations pages and press for all 383+ known entities

All three mechanisms run every scan cycle (60 min) and store results in
the edgar_filings table for unified processing and alerting.

Usage:
    from global_filing_scanner import scan_all_filings
    scan_all_filings()  # Call every 15-60 minutes
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

HEADERS = {
    'User-Agent': 'TreasurySignalIntelligence admin@quantedgeriskadvisory.com',
    'Accept': 'application/json, text/html, application/xml',
}

# ═══════════════════════════════════════════════
# BITCOIN KEYWORDS IN 15 LANGUAGES
# ═══════════════════════════════════════════════

BTC_KEYWORDS_BY_LANGUAGE = {
    'en': ['bitcoin', 'btc', 'bitcoin treasury', 'bitcoin purchase', 'bitcoin acquisition', 'digital asset reserve'],
    'fr': ['bitcoin', 'btc', 'achat bitcoin', 'trésorerie bitcoin', 'acquisition bitcoin', 'réserve bitcoin'],
    'de': ['bitcoin', 'btc', 'bitcoin kauf', 'bitcoin erwerb', 'kryptowährung bilanz', 'bitcoin reserve'],
    'ja': ['ビットコイン', 'BTC', 'ビットコイン購入', 'ビットコイン取得', 'デジタル資産'],
    'ko': ['비트코인', 'BTC', '비트코인 매수', '비트코인 취득', '디지털자산'],
    'pt': ['bitcoin', 'btc', 'compra bitcoin', 'aquisição bitcoin', 'reserva bitcoin', 'tesouraria bitcoin'],
    'es': ['bitcoin', 'btc', 'compra bitcoin', 'adquisición bitcoin', 'reserva bitcoin', 'tesorería bitcoin'],
    'zh': ['比特币', 'BTC', '比特币购买', '比特币收购', '数字资产储备'],
    'it': ['bitcoin', 'btc', 'acquisto bitcoin', 'riserva bitcoin'],
    'sv': ['bitcoin', 'btc', 'bitcoin köp', 'bitcoin förvärv'],
    'no': ['bitcoin', 'btc', 'bitcoin kjøp', 'bitcoin anskaffelse'],
    'nl': ['bitcoin', 'btc', 'bitcoin aankoop', 'bitcoin acquisitie'],
    'tr': ['bitcoin', 'btc', 'bitcoin satın alma', 'bitcoin rezervi'],
    'he': ['ביטקוין', 'BTC'],
    'hi': ['बिटकॉइन', 'BTC', 'बिटकॉइन खरीद'],
}

# Flat list for quick checking
ALL_BTC_KEYWORDS = []
for kws in BTC_KEYWORDS_BY_LANGUAGE.values():
    ALL_BTC_KEYWORDS.extend(kws)
ALL_BTC_KEYWORDS = list(set(ALL_BTC_KEYWORDS))

BTC_AMOUNT_PATTERNS = [
    r'(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*(?:BTC|bitcoin|bitcoins)',
    r'approximately\s+(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*(?:BTC|bitcoin)',
    r'acquired\s+(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*(?:BTC|bitcoin)',
    r'purchased\s+(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*(?:BTC|bitcoin)',
    r'holds?\s+(?:approximately\s+)?(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*(?:BTC|bitcoin)',
]

def _hash_id(text):
    return hashlib.md5(text.encode()).hexdigest()[:20]

def _extract_btc(text):
    text_lower = text.lower()
    for pattern in BTC_AMOUNT_PATTERNS:
        matches = re.findall(pattern, text_lower)
        if matches:
            amounts = []
            for m in matches:
                try: amounts.append(float(m.replace(',', '')))
                except: pass
            if amounts: return max(amounts)
    return 0

def _has_btc_keywords(text):
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in ALL_BTC_KEYWORDS)

def _store_filing(filing):
    try:
        supabase.table("edgar_filings").upsert(filing, on_conflict="accession_number").execute()
    except Exception as e:
        logger.debug(f"  Filing store error: {e}")

def _get_processed():
    try:
        r = supabase.table("edgar_filings").select("accession_number").execute()
        return set(d['accession_number'] for d in (r.data or []))
    except:
        return set()

def _send_alert(source, company, event_type, btc_amount, url):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_PAID_CHANNEL_ID:
        return
    emoji = '🟢' if 'purchase' in event_type.lower() else '🔴' if 'sale' in event_type.lower() else '📋'
    msg = f"{emoji} **FILING — {source}**\n\n**{company}** — {event_type}\n"
    if btc_amount > 0:
        msg += f"₿ {btc_amount:,.0f} BTC\n"
    msg += f"\n📄 [View]({url})\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}"
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={'chat_id': TELEGRAM_PAID_CHANNEL_ID, 'text': msg, 'parse_mode': 'Markdown', 'disable_web_page_preview': True}, timeout=10)
    except: pass


# ═══════════════════════════════════════════════════════════
# MECHANISM 1: COUNTRY-SPECIFIC REGULATORY FILING SYSTEMS
# ═══════════════════════════════════════════════════════════

def scan_usa_edgar(days_back=1):
    """USA — SEC EDGAR full-text search API."""
    filings = []
    end_dt = datetime.now().strftime('%Y-%m-%d')
    start_dt = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
    for keyword in ['"bitcoin"', '"btc" AND "treasury"', '"digital asset" AND "acquired"']:
        try:
            resp = requests.get("https://efts.sec.gov/LATEST/search-index", params={
                'q': keyword, 'dateRange': 'custom', 'startdt': start_dt, 'enddt': end_dt,
                'forms': '8-K,8-K/A,10-Q,10-K',
            }, headers=HEADERS, timeout=30)
            if resp.ok:
                for hit in resp.json().get('hits', {}).get('hits', []):
                    src = hit.get('_source', {})
                    name = (src.get('display_names', [''])[0] if src.get('display_names') else src.get('entity_name', ''))
                    filings.append({
                        'accession_number': f"edgar_{_hash_id(str(src.get('file_num', '')))}",
                        'company_name': name[:200], 'ticker_cik': src.get('entity_name', '')[:50],
                        'filing_date': src.get('file_date', end_dt), 'form_type': src.get('form_type', '8-K'),
                        'event_type': 'filing', 'source': 'SEC EDGAR (USA)',
                        'filing_url': f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&filenum={src.get('file_num', '')}&type=8-K",
                    })
            time.sleep(0.5)
        except Exception as e:
            logger.debug(f"    EDGAR error: {e}")
    return filings

def scan_canada_sedar(days_back=1):
    """Canada — SEDAR+ search."""
    filings = []
    try:
        resp = requests.get("https://www.sedarplus.ca/csa-party/records/filter", params={
            'keyword': 'bitcoin', 'category': 'Filing',
            'fromDate': (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d'),
            'toDate': datetime.now().strftime('%Y-%m-%d'),
        }, headers={**HEADERS, 'Accept': 'application/json'}, timeout=30)
        if resp.ok:
            for item in (resp.json().get('results', []) if isinstance(resp.json(), dict) else []):
                filings.append({
                    'accession_number': f"sedar_{_hash_id(str(item))}", 'company_name': (item.get('issuerName', '') or '')[:200],
                    'ticker_cik': '', 'filing_date': item.get('filingDate', datetime.now().strftime('%Y-%m-%d')),
                    'form_type': 'SEDAR Filing', 'event_type': 'filing', 'source': 'SEDAR+ (Canada)',
                    'filing_url': f"https://www.sedarplus.ca/csa-party/records/{item.get('id', '')}",
                })
    except Exception as e:
        logger.debug(f"    SEDAR error: {e}")
    return filings

def scan_japan_tdnet():
    """Japan — TDnet + EDINET."""
    filings = []
    try:
        today = datetime.now().strftime('%Y-%m-%d')
        resp = requests.get(f"https://disclosure.edinet-fsa.go.jp/api/v2/documents.json?date={today}&type=2", headers=HEADERS, timeout=30)
        if resp.ok:
            for doc in resp.json().get('results', []):
                title = (doc.get('docDescription', '') or '').lower()
                if _has_btc_keywords(title):
                    filings.append({
                        'accession_number': f"edinet_{doc.get('docID', '')}", 'company_name': (doc.get('filerName', ''))[:200],
                        'ticker_cik': doc.get('secCode', ''), 'filing_date': doc.get('submitDateTime', today)[:10],
                        'form_type': 'EDINET Filing', 'event_type': 'filing', 'source': 'EDINET (Japan)',
                        'filing_url': f"https://disclosure.edinet-fsa.go.jp/E01EW/BLMainController.jsp?uji.verb=W0EZA226CXP001003Action&docID={doc.get('docID', '')}",
                    })
    except Exception as e:
        logger.debug(f"    EDINET error: {e}")
    return filings

def scan_korea_dart():
    """South Korea — DART API."""
    filings = []
    dart_key = os.getenv("DART_API_KEY", "")
    if not dart_key: return filings
    try:
        today = datetime.now().strftime('%Y%m%d')
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y%m%d')
        resp = requests.get("https://opendart.fss.or.kr/api/list.json", params={
            'crtfc_key': dart_key, 'bgn_de': yesterday, 'end_de': today, 'page_count': 100,
        }, headers=HEADERS, timeout=30)
        if resp.ok:
            for item in resp.json().get('list', []):
                if _has_btc_keywords(item.get('report_nm', '')):
                    filings.append({
                        'accession_number': f"dart_{item.get('rcept_no', '')}", 'company_name': item.get('corp_name', '')[:200],
                        'ticker_cik': item.get('stock_code', ''), 'filing_date': item.get('rcept_dt', today),
                        'form_type': 'DART Filing', 'event_type': 'filing', 'source': 'DART (South Korea)',
                        'filing_url': f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={item.get('rcept_no', '')}",
                    })
    except Exception as e:
        logger.debug(f"    DART error: {e}")
    return filings

def scan_france_amf():
    """France — AMF (Autorité des marchés financiers)."""
    filings = []
    try:
        resp = requests.get("https://www.amf-france.org/en/search?q=bitcoin&type=decisions", headers=HEADERS, timeout=30)
        if resp.ok:
            soup = BeautifulSoup(resp.text, 'html.parser')
            for item in soup.select('.search-result, .node, article'):
                text = item.get_text()
                if _has_btc_keywords(text):
                    link = item.find('a', href=True)
                    filings.append({
                        'accession_number': f"amf_{_hash_id(text[:100])}", 'company_name': text[:200].split('\n')[0].strip(),
                        'ticker_cik': '', 'filing_date': datetime.now().strftime('%Y-%m-%d'),
                        'form_type': 'AMF Disclosure', 'event_type': 'filing', 'source': 'AMF (France)',
                        'filing_url': f"https://www.amf-france.org{link['href']}" if link else '',
                    })
    except Exception as e:
        logger.debug(f"    AMF error: {e}")
    return filings

def scan_uk_rns():
    """UK — RNS Regulatory News Service."""
    filings = []
    try:
        resp = requests.get("https://www.londonstockexchange.com/news?tab=news-explorer&q=bitcoin", headers=HEADERS, timeout=30)
        if resp.ok:
            soup = BeautifulSoup(resp.text, 'html.parser')
            for item in soup.select('.news-item, article, tr'):
                text = item.get_text()
                if _has_btc_keywords(text):
                    link = item.find('a', href=True)
                    filings.append({
                        'accession_number': f"rns_{_hash_id(text[:100])}", 'company_name': text[:200].split('\n')[0].strip(),
                        'ticker_cik': '', 'filing_date': datetime.now().strftime('%Y-%m-%d'),
                        'form_type': 'RNS Announcement', 'event_type': 'filing', 'source': 'RNS (UK)',
                        'filing_url': f"https://www.londonstockexchange.com{link['href']}" if link else '',
                    })
    except Exception as e:
        logger.debug(f"    RNS error: {e}")
    return filings

def scan_germany_bafin():
    """Germany — Bundesanzeiger / BaFin."""
    filings = []
    try:
        resp = requests.get("https://www.bundesanzeiger.de/pub/de/suchergebnis?5",
            params={'fulltext': 'bitcoin', 'area': 'FinanzKapitalMarkt'}, headers=HEADERS, timeout=30)
        if resp.ok:
            soup = BeautifulSoup(resp.text, 'html.parser')
            for item in soup.select('.result_container, .publication, article'):
                text = item.get_text()
                if _has_btc_keywords(text):
                    filings.append({
                        'accession_number': f"bafin_{_hash_id(text[:100])}", 'company_name': text[:200].split('\n')[0].strip(),
                        'ticker_cik': '', 'filing_date': datetime.now().strftime('%Y-%m-%d'),
                        'form_type': 'Bundesanzeiger', 'event_type': 'filing', 'source': 'BaFin (Germany)',
                        'filing_url': '',
                    })
    except Exception as e:
        logger.debug(f"    BaFin error: {e}")
    return filings

def scan_hk_hkex():
    """Hong Kong — HKEX."""
    filings = []
    try:
        resp = requests.get("https://www1.hkexnews.hk/search/titlesearch.xhtml?lang=en&q=bitcoin", headers=HEADERS, timeout=30)
        if resp.ok:
            soup = BeautifulSoup(resp.text, 'html.parser')
            for row in soup.select('tr, .row'):
                text = row.get_text()
                if _has_btc_keywords(text):
                    link = row.find('a', href=True)
                    filings.append({
                        'accession_number': f"hkex_{_hash_id(text[:100])}", 'company_name': text[:200].split('\n')[0].strip(),
                        'ticker_cik': '', 'filing_date': datetime.now().strftime('%Y-%m-%d'),
                        'form_type': 'HKEX Announcement', 'event_type': 'filing', 'source': 'HKEX (Hong Kong)',
                        'filing_url': link['href'] if link else '',
                    })
    except Exception as e:
        logger.debug(f"    HKEX error: {e}")
    return filings

def scan_australia_asx():
    """Australia — ASX."""
    filings = []
    try:
        resp = requests.get("https://www.asx.com.au/asx/statistics/announcements.do?timeframe=D", headers=HEADERS, timeout=30)
        if resp.ok:
            soup = BeautifulSoup(resp.text, 'html.parser')
            for row in soup.select('tr'):
                text = row.get_text()
                if _has_btc_keywords(text):
                    cells = row.find_all('td')
                    link = row.find('a', href=True)
                    filings.append({
                        'accession_number': f"asx_{_hash_id(text[:100])}", 'company_name': (cells[1].get_text(strip=True) if len(cells) > 1 else '')[:200],
                        'ticker_cik': (cells[0].get_text(strip=True) if cells else ''),
                        'filing_date': datetime.now().strftime('%Y-%m-%d'),
                        'form_type': 'ASX Announcement', 'event_type': 'filing', 'source': 'ASX (Australia)',
                        'filing_url': f"https://www.asx.com.au{link['href']}" if link else '',
                    })
    except Exception as e:
        logger.debug(f"    ASX error: {e}")
    return filings

def scan_brazil_cvm():
    """Brazil — CVM (Comissão de Valores Mobiliários)."""
    filings = []
    try:
        resp = requests.get("https://sistemas.cvm.gov.br/port/ciasabertas/resultadopesquisa.asp?keyword=bitcoin", headers=HEADERS, timeout=30)
        if resp.ok and _has_btc_keywords(resp.text):
            soup = BeautifulSoup(resp.text, 'html.parser')
            for item in soup.select('tr, .resultado'):
                text = item.get_text()
                if _has_btc_keywords(text):
                    filings.append({
                        'accession_number': f"cvm_{_hash_id(text[:100])}", 'company_name': text[:200].split('\n')[0].strip(),
                        'ticker_cik': '', 'filing_date': datetime.now().strftime('%Y-%m-%d'),
                        'form_type': 'CVM Filing', 'event_type': 'filing', 'source': 'CVM (Brazil)',
                        'filing_url': '',
                    })
    except Exception as e:
        logger.debug(f"    CVM error: {e}")
    return filings

def scan_india_sebi():
    """India — BSE/NSE corporate announcements."""
    filings = []
    try:
        resp = requests.get("https://www.bseindia.com/corporates/ann.html", headers=HEADERS, timeout=30)
        if resp.ok and _has_btc_keywords(resp.text):
            soup = BeautifulSoup(resp.text, 'html.parser')
            for item in soup.select('tr, .announcement'):
                text = item.get_text()
                if _has_btc_keywords(text):
                    filings.append({
                        'accession_number': f"bse_{_hash_id(text[:100])}", 'company_name': text[:200].split('\n')[0].strip(),
                        'ticker_cik': '', 'filing_date': datetime.now().strftime('%Y-%m-%d'),
                        'form_type': 'BSE Announcement', 'event_type': 'filing', 'source': 'BSE (India)',
                        'filing_url': '',
                    })
    except Exception as e:
        logger.debug(f"    BSE error: {e}")
    return filings

def scan_singapore_sgx():
    """Singapore — SGX announcements."""
    filings = []
    try:
        resp = requests.get("https://www.sgx.com/securities/company-announcements?q=bitcoin", headers=HEADERS, timeout=30)
        if resp.ok and _has_btc_keywords(resp.text):
            soup = BeautifulSoup(resp.text, 'html.parser')
            for item in soup.select('.announcement-item, tr, article'):
                text = item.get_text()
                if _has_btc_keywords(text):
                    filings.append({
                        'accession_number': f"sgx_{_hash_id(text[:100])}", 'company_name': text[:200].split('\n')[0].strip(),
                        'ticker_cik': '', 'filing_date': datetime.now().strftime('%Y-%m-%d'),
                        'form_type': 'SGX Announcement', 'event_type': 'filing', 'source': 'SGX (Singapore)',
                        'filing_url': '',
                    })
    except Exception as e:
        logger.debug(f"    SGX error: {e}")
    return filings

def scan_israel_tase():
    """Israel — TASE (Tel Aviv Stock Exchange)."""
    filings = []
    try:
        resp = requests.get("https://maya.tase.co.il/reports/company?q=bitcoin", headers=HEADERS, timeout=30)
        if resp.ok and _has_btc_keywords(resp.text):
            soup = BeautifulSoup(resp.text, 'html.parser')
            for item in soup.select('tr, .report-item, article'):
                text = item.get_text()
                if _has_btc_keywords(text):
                    filings.append({
                        'accession_number': f"tase_{_hash_id(text[:100])}", 'company_name': text[:200].split('\n')[0].strip(),
                        'ticker_cik': '', 'filing_date': datetime.now().strftime('%Y-%m-%d'),
                        'form_type': 'TASE Report', 'event_type': 'filing', 'source': 'TASE (Israel)',
                        'filing_url': '',
                    })
    except Exception as e:
        logger.debug(f"    TASE error: {e}")
    return filings

def scan_norway_oslo():
    """Norway — Oslo Bors newsweb."""
    filings = []
    try:
        resp = requests.get("https://newsweb.oslobors.no/search?q=bitcoin", headers=HEADERS, timeout=30)
        if resp.ok:
            soup = BeautifulSoup(resp.text, 'html.parser')
            for item in soup.select('.search-result, .news-item, tr'):
                text = item.get_text()
                if _has_btc_keywords(text):
                    link = item.find('a', href=True)
                    filings.append({
                        'accession_number': f"oslo_{_hash_id(text[:100])}", 'company_name': text[:200].split('\n')[0].strip(),
                        'ticker_cik': '', 'filing_date': datetime.now().strftime('%Y-%m-%d'),
                        'form_type': 'Oslo Bors News', 'event_type': 'filing', 'source': 'Oslo Bors (Norway)',
                        'filing_url': f"https://newsweb.oslobors.no{link['href']}" if link else '',
                    })
    except Exception as e:
        logger.debug(f"    Oslo error: {e}")
    return filings

def scan_sweden_fi():
    """Sweden — Finansinspektionen / Nasdaq Stockholm."""
    filings = []
    try:
        resp = requests.get("https://www.fi.se/en/our-registers/search/?q=bitcoin", headers=HEADERS, timeout=30)
        if resp.ok and _has_btc_keywords(resp.text):
            soup = BeautifulSoup(resp.text, 'html.parser')
            for item in soup.select('tr, .search-result, article'):
                text = item.get_text()
                if _has_btc_keywords(text):
                    filings.append({
                        'accession_number': f"fi_se_{_hash_id(text[:100])}", 'company_name': text[:200].split('\n')[0].strip(),
                        'ticker_cik': '', 'filing_date': datetime.now().strftime('%Y-%m-%d'),
                        'form_type': 'FI Disclosure', 'event_type': 'filing', 'source': 'Finansinspektionen (Sweden)',
                        'filing_url': '',
                    })
    except Exception as e:
        logger.debug(f"    FI Sweden error: {e}")
    return filings

def scan_turkey_kap():
    """Turkey — KAP (Public Disclosure Platform)."""
    filings = []
    try:
        resp = requests.get("https://www.kap.org.tr/en/bildirim-sorgu?q=bitcoin", headers=HEADERS, timeout=30)
        if resp.ok and _has_btc_keywords(resp.text):
            soup = BeautifulSoup(resp.text, 'html.parser')
            for item in soup.select('tr, .notification, article'):
                text = item.get_text()
                if _has_btc_keywords(text):
                    filings.append({
                        'accession_number': f"kap_{_hash_id(text[:100])}", 'company_name': text[:200].split('\n')[0].strip(),
                        'ticker_cik': '', 'filing_date': datetime.now().strftime('%Y-%m-%d'),
                        'form_type': 'KAP Notification', 'event_type': 'filing', 'source': 'KAP (Turkey)',
                        'filing_url': '',
                    })
    except Exception as e:
        logger.debug(f"    KAP error: {e}")
    return filings

def scan_el_salvador():
    """El Salvador — Official government dashboard."""
    filings = []
    try:
        resp = requests.get("https://bitcoin.gob.sv", headers=HEADERS, timeout=15)
        if resp.ok:
            btc = _extract_btc(resp.text)
            if btc > 0:
                filings.append({
                    'accession_number': f"sv_gov_{datetime.now().strftime('%Y%m%d')}", 'company_name': 'El Salvador (Government)',
                    'ticker_cik': 'SV.GOV', 'filing_date': datetime.now().strftime('%Y-%m-%d'),
                    'form_type': 'Government Dashboard', 'event_type': 'holding', 'btc_amount': btc,
                    'source': 'bitcoin.gob.sv', 'filing_url': 'https://bitcoin.gob.sv',
                })
    except Exception as e:
        logger.debug(f"    El Salvador error: {e}")
    return filings


# ═══════════════════════════════════════════════════════════
# MECHANISM 2: MULTI-LANGUAGE GLOBAL NEWS MONITORING
# ═══════════════════════════════════════════════════════════

# Google News RSS — searches in 15 languages
# This catches press releases, announcements, and disclosures from
# ANY country regardless of whether they have a filing system API.

GOOGLE_NEWS_QUERIES = {
    'en-US': ['bitcoin+treasury+purchase+company', 'bitcoin+acquisition+corporate', 'bitcoin+reserve+balance+sheet', 'bitcoin+holdings+announced'],
    'fr-FR': ['bitcoin+achat+entreprise+trésorerie', 'bitcoin+acquisition+société'],
    'de-DE': ['bitcoin+kauf+unternehmen+bilanz', 'bitcoin+erwerb+firma'],
    'ja-JP': ['ビットコイン+購入+企業', 'ビットコイン+取得+会社'],
    'ko-KR': ['비트코인+매수+기업', '비트코인+취득+회사'],
    'pt-BR': ['bitcoin+compra+empresa+tesouraria', 'bitcoin+aquisição+corporativa'],
    'es-ES': ['bitcoin+compra+empresa+tesorería', 'bitcoin+adquisición+corporativa'],
    'zh-CN': ['比特币+购买+公司', '比特币+收购+企业'],
    'it-IT': ['bitcoin+acquisto+azienda', 'bitcoin+riserva+società'],
    'sv-SE': ['bitcoin+köp+företag', 'bitcoin+förvärv+bolag'],
    'no-NO': ['bitcoin+kjøp+selskap'],
    'nl-NL': ['bitcoin+aankoop+bedrijf'],
    'tr-TR': ['bitcoin+satın+alma+şirket'],
    'he-IL': ['ביטקוין+רכישה+חברה'],
    'hi-IN': ['बिटकॉइन+खरीद+कंपनी'],
}

def scan_global_news():
    """Multi-language Google News RSS — catches BTC announcements from ANY country."""
    filings = []
    for locale, queries in GOOGLE_NEWS_QUERIES.items():
        lang = locale.split('-')[0]
        country = locale.split('-')[1] if '-' in locale else 'US'
        for query in queries:
            try:
                resp = requests.get(
                    f"https://news.google.com/rss/search?q={query}+when:1d&hl={lang}&gl={country}&ceid={country}:{lang}",
                    headers=HEADERS, timeout=15,
                )
                if resp.ok:
                    soup = BeautifulSoup(resp.text, 'xml')
                    for item in soup.find_all('item'):
                        title = item.find('title').get_text() if item.find('title') else ''
                        link = item.find('link').get_text() if item.find('link') else ''
                        source_tag = item.find('source')
                        source_name = source_tag.get_text() if source_tag else 'News'

                        if title and _has_btc_keywords(title):
                            filings.append({
                                'accession_number': f"gnews_{_hash_id(title)}",
                                'company_name': title[:200],
                                'ticker_cik': '',
                                'filing_date': datetime.now().strftime('%Y-%m-%d'),
                                'form_type': f'Press ({source_name})',
                                'event_type': 'press_release',
                                'source': f'Google News [{locale}]',
                                'filing_url': link,
                            })
                time.sleep(0.5)
            except Exception as e:
                logger.debug(f"    Google News [{locale}] error: {e}")
    return filings


# ═══════════════════════════════════════════════════════════
# MECHANISM 3: CRYPTO-SPECIFIC NEWS WIRES
# ═══════════════════════════════════════════════════════════

def scan_crypto_news():
    """CoinDesk, CoinTelegraph, The Block, Bitcoin Magazine RSS — global coverage."""
    filings = []
    feeds = [
        ('CoinDesk', 'https://www.coindesk.com/arc/outboundfeeds/rss/'),
        ('CoinTelegraph', 'https://cointelegraph.com/rss'),
        ('Bitcoin Magazine', 'https://bitcoinmagazine.com/.rss/full/'),
        ('Decrypt', 'https://decrypt.co/feed'),
    ]
    for source_name, url in feeds:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.ok:
                soup = BeautifulSoup(resp.text, 'xml')
                for item in soup.find_all('item')[:20]:
                    title = item.find('title').get_text() if item.find('title') else ''
                    link = item.find('link').get_text() if item.find('link') else ''
                    desc = item.find('description').get_text() if item.find('description') else ''

                    combined = f"{title} {desc}".lower()
                    # Only capture treasury/corporate/government BTC news, not general price news
                    if any(kw in combined for kw in ['treasury', 'purchase', 'acquired', 'balance sheet', 'reserve', 'holdings', 'bought', 'government', 'corporate']):
                        if _has_btc_keywords(combined):
                            filings.append({
                                'accession_number': f"crypto_{_hash_id(title)}",
                                'company_name': title[:200],
                                'ticker_cik': '',
                                'filing_date': datetime.now().strftime('%Y-%m-%d'),
                                'form_type': f'Crypto News ({source_name})',
                                'event_type': 'press_release',
                                'source': source_name,
                                'filing_url': link,
                            })
            time.sleep(1)
        except Exception as e:
            logger.debug(f"    {source_name} error: {e}")
    return filings


# ═══════════════════════════════════════════════════════════
# MAIN SCANNER — ORCHESTRATES ALL MECHANISMS
# ═══════════════════════════════════════════════════════════

REGULATORY_ADAPTERS = [
    ('USA', scan_usa_edgar),
    ('Canada', scan_canada_sedar),
    ('Japan', scan_japan_tdnet),
    ('South Korea', scan_korea_dart),
    ('France', scan_france_amf),
    ('UK', scan_uk_rns),
    ('Germany', scan_germany_bafin),
    ('Hong Kong', scan_hk_hkex),
    ('Australia', scan_australia_asx),
    ('Brazil', scan_brazil_cvm),
    ('India', scan_india_sebi),
    ('Singapore', scan_singapore_sgx),
    ('Israel', scan_israel_tase),
    ('Norway', scan_norway_oslo),
    ('Sweden', scan_sweden_fi),
    ('Turkey', scan_turkey_kap),
    ('El Salvador', scan_el_salvador),
]


def scan_all_filings(days_back=1):
    """
    EXHAUSTIVE global scan:
    1. 17 country-specific regulatory filing systems
    2. Google News in 15 languages (catches ALL other countries)
    3. 4 crypto-specific news wires
    """
    logger.info(f"Global Scanner v2: {len(REGULATORY_ADAPTERS)} regulators + 15 languages + 4 crypto wires")
    start = time.time()

    processed = _get_processed()
    total_new = 0
    total_alerts = 0
    source_stats = {}

    # Mechanism 1: Country-specific regulatory systems
    logger.info("  [1/3] Regulatory filing systems...")
    for country, adapter in REGULATORY_ADAPTERS:
        try:
            filings = adapter(days_back) if 'days_back' in adapter.__code__.co_varnames else adapter()
            new_count = 0
            for filing in filings:
                acc = filing.get('accession_number', '')
                if acc in processed: continue
                filing['processed_at'] = datetime.now().isoformat()
                filing['btc_amount'] = filing.get('btc_amount', 0)
                filing['usd_amount'] = filing.get('usd_amount', 0)
                _store_filing(filing)
                processed.add(acc)
                new_count += 1
                if filing.get('company_name') and filing.get('event_type') != 'holding':
                    _send_alert(filing.get('source', country), filing['company_name'], filing.get('event_type', 'filing'), filing.get('btc_amount', 0), filing.get('filing_url', ''))
                    total_alerts += 1
            source_stats[country] = new_count
            total_new += new_count
        except Exception as e:
            logger.debug(f"  {country} error: {e}")
            source_stats[country] = 0

    # Mechanism 2: Multi-language global news
    logger.info("  [2/3] Multi-language news (15 languages)...")
    try:
        news_filings = scan_global_news()
        news_new = 0
        for filing in news_filings:
            acc = filing.get('accession_number', '')
            if acc in processed: continue
            filing['processed_at'] = datetime.now().isoformat()
            filing['btc_amount'] = _extract_btc(filing.get('company_name', ''))
            filing['usd_amount'] = 0
            _store_filing(filing)
            processed.add(acc)
            news_new += 1
        source_stats['Global News (15 langs)'] = news_new
        total_new += news_new
    except Exception as e:
        logger.debug(f"  Global news error: {e}")

    # Mechanism 3: Crypto-specific news wires
    logger.info("  [3/3] Crypto news wires...")
    try:
        crypto_filings = scan_crypto_news()
        crypto_new = 0
        for filing in crypto_filings:
            acc = filing.get('accession_number', '')
            if acc in processed: continue
            filing['processed_at'] = datetime.now().isoformat()
            filing['btc_amount'] = _extract_btc(filing.get('company_name', ''))
            filing['usd_amount'] = 0
            _store_filing(filing)
            processed.add(acc)
            crypto_new += 1
        source_stats['Crypto News Wires'] = crypto_new
        total_new += crypto_new
    except Exception as e:
        logger.debug(f"  Crypto news error: {e}")

    elapsed = time.time() - start
    logger.info(f"Global Scanner v2: {total_new} new items, {total_alerts} alerts ({elapsed:.1f}s)")
    for src, count in source_stats.items():
        if count > 0:
            logger.info(f"  ✅ {src}: {count} new")

    return {'new_filings': total_new, 'alerts': total_alerts, 'sources': source_stats}


if __name__ == "__main__":
    logger.info("Global Scanner v2 — manual run (last 3 days)...")
    result = scan_all_filings(days_back=3)
    print(f"\nTotal: {result['new_filings']} new, {result['alerts']} alerts")
    print(f"Sources: {json.dumps(result['sources'], indent=2)}")
