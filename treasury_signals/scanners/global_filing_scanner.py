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
    from treasury_signals.scanners.global_filing_scanner import scan_all_filings
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
from treasury_signals.logger import get_logger

try:
    from treasury_signals.pipelines.purchase_reconciler import reconcile_and_save, reconcile_sale
    HAS_RECONCILER = True
except ImportError:
    HAS_RECONCILER = False

from treasury_signals.observability import capture_exception

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

_OPTIONAL_EDGAR_COLS = ('acceptance_datetime', 'alerted_at')


def _store_filing(filing):
    try:
        supabase.table("edgar_filings").upsert(filing, on_conflict="accession_number").execute()
        return
    except Exception as e:
        # Forward-compat: if migration 0023 (acceptance_datetime) isn't applied
        # yet, drop those keys and retry so the filing still lands.
        s = str(e).lower()
        if ('column' in s and ('does not exist' in s or 'could not find' in s or 'schema cache' in s)
                and any(k in filing for k in _OPTIONAL_EDGAR_COLS)):
            trimmed = {k: v for k, v in filing.items() if k not in _OPTIONAL_EDGAR_COLS}
            try:
                supabase.table("edgar_filings").upsert(trimmed, on_conflict="accession_number").execute()
                logger.warning("  Filing store: acceptance_datetime column absent — stored without it (apply migration 0023)")
                return
            except Exception as e2:
                e = e2
        # Promoted from logger.debug — this is the swallow that hid the missing
        # `source` column for 28+ days. Schema mismatches must be loud.
        logger.warning(f"  Filing store error: {e} (accession={filing.get('accession_number','')}, source={filing.get('source','')})")
        capture_exception(e, context={
            "where": "global_filing_scanner._store_filing",
            "accession": filing.get("accession_number", ""),
            "source": filing.get("source", ""),
            "company": filing.get("company_name", "")[:80],
        })

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


def _resolve_ticker_for_reconciler(company_name):
    """Resolve a company name from filings to our database ticker."""
    if not company_name:
        return company_name, ""
    try:
        result = supabase.table("treasury_companies").select("company, ticker").gt("btc_holdings", 0).execute()
        if not result.data:
            return company_name, ""
        name_clean = re.sub(r'[^\x20-\x7E]', '', company_name).upper().strip()
        for suffix in [' INC', ' INC.', ' CORP', ' CORP.', ' LTD', ' LTD.', ' LLC', ' PLC', ' CO', ' CO.',
                       ' GROUP', ' HOLDINGS', ' GLOBAL', ' K.K.', ' AG', ' SE', ' SA', ' LIMITED', ',']:
            name_clean = name_clean.replace(suffix, '')
        name_clean = name_clean.strip()
        for row in result.data:
            db_name = re.sub(r'[^\x20-\x7E]', '', (row.get('company', '') or '')).upper().strip()
            for suffix in [' INC', ' INC.', ' CORP', ' CORP.', ' LTD', ' LTD.', ' LLC', ' PLC', ' CO', ' CO.',
                           ' GROUP', ' HOLDINGS', ' GLOBAL', ' (MICROSTRATEGY)', ',']:
                db_name = db_name.replace(suffix, '')
            db_name = db_name.strip()
            if name_clean == db_name:
                return row['company'], row['ticker']
            if name_clean and db_name and (name_clean in db_name or db_name in name_clean):
                if min(len(name_clean), len(db_name)) / max(len(name_clean), len(db_name), 1) > 0.5:
                    return row['company'], row['ticker']
    except:
        pass
    return company_name, ""


def _route_to_reconciler(filing):
    """
    Route a filing with btc_amount > 0 through the purchase reconciler.
    
    Validation (matches EDGAR-level rigor):
      1. Must have btc_amount > 0
      2. Must have btc_amount >= 10 (filter noise)
      3. Company must resolve to a known entity in treasury_companies
      4. Event must look like a purchase (not just a mention)
      5. Filing URL must be the original international source (not EDGAR)
    """
    if not HAS_RECONCILER:
        return
    btc = float(filing.get('btc_amount', 0))
    if btc < 10:  # Filter noise — less than 10 BTC is likely a false positive
        return

    company = filing.get('company_name', '')
    source = filing.get('source', '')

    # CRITICAL VALIDATION: Company must exist in our treasury_companies database
    # This prevents false positives like "Peter Schiff" or random news mentions
    resolved_name, resolved_ticker = _resolve_ticker_for_reconciler(company)
    if not resolved_ticker:
        logger.debug(f"  {source}: '{company}' not found in treasury_companies — skipping reconciler")
        return

    # Validate event looks like a purchase (not sale, not just a mention)
    text = f"{company} {filing.get('event_type', '')} {filing.get('form_type', '')}".lower()
    sale_words = ['sold', 'sale', 'disposed', 'liquidated', 'reduced', 'divested']
    is_sale = any(sw in text for sw in sale_words)

    usd = float(filing.get('usd_amount', 0))
    filing_date = filing.get('filing_date', '')
    filing_url = filing.get('filing_url', '')

    # Ensure filing_url points to the international source, not EDGAR
    if not filing_url or 'edgar' in filing_url.lower():
        filing_url = ''  # Let the frontend handle the source link by entity type

    transaction = {
        "company": resolved_name,
        "ticker": resolved_ticker,
        "btc_amount": btc,
        "usd_amount": usd,
        "price_per_btc": round(usd / btc) if btc > 0 and usd > 0 else 0,
        "filing_date": filing_date or datetime.now().strftime('%Y-%m-%d'),
        "filing_url": filing_url,
        "source": f"Global Filing: {source}",
        "notes": f"Accession: {filing.get('accession_number', '')}. Source system: {source}",
    }
    try:
        if is_sale:
            result = reconcile_sale(transaction, source_type="global_filing")
            logger.info(f"  {source} → Sale Reconciler: {resolved_name} ({resolved_ticker}) — {result['action']}")
        else:
            result = reconcile_and_save(transaction, source_type="global_filing", is_new_entrant=False)
            logger.info(f"  {source} → Reconciler: {resolved_name} ({resolved_ticker}) — {result['action']}")
    except Exception as e:
        # Reconciler errors mean we have a parsed filing but failed to write it
        # — surface loudly. This used to be debug.
        logger.warning(f"  Reconciler routing error: {e} (source={source}, company={resolved_name})")
        capture_exception(e, context={
            "where": "global_filing_scanner._route_to_reconciler",
            "source": source,
            "company": resolved_name,
            "ticker": resolved_ticker,
            "btc": btc,
        })


# ═══════════════════════════════════════════════════════════
# MECHANISM 1: COUNTRY-SPECIFIC REGULATORY FILING SYSTEMS
# ═══════════════════════════════════════════════════════════

_tracked_cik_cache = {}


def _tracked_ciks():
    """Map CIK(int) -> ticker for US-listed tracked BTC holders.

    Built from treasury_companies tickers resolved through SEC's official
    ticker->CIK file. We match the getcurrent feed by EXACT CIK rather than the
    fuzzy company-name matcher, which produces false positives (e.g. 'Strategy
    Inc' mis-resolving to an unrelated ticker). International holders that don't
    file 8-Ks simply won't appear in SEC's file, which is fine. Cached per process.
    """
    if _tracked_cik_cache:
        return _tracked_cik_cache
    try:
        tracked = supabase.table("treasury_companies").select("ticker").gt("btc_holdings", 0).execute().data or []
        # strip exchange suffixes (HAMA.L -> HAMA) so US tickers line up
        tickers = {(t.get("ticker") or "").upper().split(".")[0] for t in tracked if t.get("ticker")}
        resp = requests.get("https://www.sec.gov/files/company_tickers.json", headers=HEADERS, timeout=30)
        resp.raise_for_status()
        for row in resp.json().values():
            tk = (row.get("ticker") or "").upper()
            if tk in tickers:
                _tracked_cik_cache[int(row["cik_str"])] = tk
        logger.debug(f"    tracked CIK map: {len(_tracked_cik_cache)} US holders resolved")
    except Exception as e:
        logger.warning(f"    tracked CIK map build failed: {e}")
    return _tracked_cik_cache


def scan_usa_edgar_atom(days_back=1):
    """USA — SEC EDGAR latest-filings Atom feed (8-K). Catches filings within
    seconds of acceptance, before the full-text search API indexes them.

    The getcurrent feed's title/summary carry only the company name, CIK, accession
    and item numbers — never the document body — so the old BTC-keyword gate on
    that metadata matched almost nothing and the feed logged empty. The real
    early-warning signal is: a company WE ALREADY TRACK as a BTC holder just filed
    an 8-K. So we trigger on (a) a tracked-company match (primary) OR (b) a BTC
    keyword in the metadata (rare, but catches an obvious new entrant). The
    excerpt extractor then fetches the document and confirms the actual content.
    """
    filings = []
    try:
        resp = requests.get(
            "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&output=atom",
            headers=HEADERS, timeout=30,
        )
        if not resp.ok:
            return filings
        soup = BeautifulSoup(resp.text, 'xml')
        cutoff = datetime.now() - timedelta(days=max(days_back, 1))
        for entry in soup.find_all('entry'):
            title = (entry.find('title').get_text() if entry.find('title') else '').strip()
            updated = (entry.find('updated').get_text() if entry.find('updated') else '').strip()
            link_tag = entry.find('link')
            href = link_tag.get('href') if link_tag else ''
            summary = (entry.find('summary').get_text() if entry.find('summary') else '').strip()

            ts = None
            try:
                ts = datetime.fromisoformat(updated.replace('Z', '+00:00')).replace(tzinfo=None)
                if ts < cutoff:
                    continue
            except Exception:
                pass

            # Title shape: "8-K - Company Name Inc. (0001502557) (Filer)".
            # Pull the CIK (exact trigger) and strip it for a clean display name.
            cik_m = re.search(r'\((\d{4,10})\)\s*\((?:Filer|Subject)\)', title)
            filer_cik = int(cik_m.group(1)) if cik_m else None
            raw = title.split(' - ', 1)[1].strip() if ' - ' in title else title
            company = re.sub(r'\s*\(\d{4,10}\)\s*\(Filer\)\s*$', '', raw)
            company = re.sub(r'\s*\((?:Filer|Subject)\)\s*$', '', company).strip() or raw[:200]

            # Primary trigger: exact CIK match against a tracked BTC holder.
            # Secondary: a BTC keyword in the metadata (rare — catches a new entrant).
            tracked_ticker = _tracked_ciks().get(filer_cik) if filer_cik else None
            keyword_hit = _has_btc_keywords(f"{title} {summary}".lower())
            if not tracked_ticker and not keyword_hit:
                continue

            accno_m = re.search(r'AccNo:\s*</b>\s*(\S+)', summary) or re.search(r'(\d{10}-\d{2}-\d{6})', summary)
            accession = accno_m.group(1) if accno_m else (href or title)
            filings.append({
                'accession_number': accession if accno_m else f"edgar_atom_{_hash_id(href or title)}",
                'company_name': company[:200],
                'ticker_cik': tracked_ticker or '',
                'filing_date': (ts.strftime('%Y-%m-%d') if ts else datetime.now().strftime('%Y-%m-%d')),
                'form_type': '8-K',
                'event_type': 'filing',
                'source': 'SEC EDGAR Atom (USA)',
                'filing_url': href,
                # acceptance timestamp from the feed — used for file→alert latency.
                'acceptance_datetime': (ts.isoformat() if ts else None),
            })
        logger.info(f"    USA-Atom: {len(filings)} BTC-relevant 8-K(s) of recent EDGAR getcurrent feed")
    except Exception as e:
        logger.warning(f"    EDGAR atom error: {e}")
    return filings


def scan_usa_edgar(days_back=1):
    """USA — SEC EDGAR full-text search API."""
    filings = []
    end_dt = datetime.now().strftime('%Y-%m-%d')
    start_dt = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
    # One request per form: EFTS silently collapses any `forms` value containing
    # a slashed amendment form ("8-K/A") to ~1 hit while still returning HTTP 200.
    # See the EDGAR_FORMS note in scanners/edgar_realtime.py for the full diagnosis.
    seen_ids = set()
    for keyword in ['"bitcoin"', '"btc" AND "treasury"', '"digital asset" AND "acquired"']:
        for form in ['8-K', '8-K/A', '10-Q', '10-K']:
            try:
                resp = requests.get("https://efts.sec.gov/LATEST/search-index", params={
                    'q': keyword, 'dateRange': 'custom', 'startdt': start_dt, 'enddt': end_dt,
                    'forms': form,
                }, headers=HEADERS, timeout=30)
                if resp.ok:
                    for hit in resp.json().get('hits', {}).get('hits', []):
                        hit_id = hit.get('_id')
                        if hit_id and hit_id in seen_ids:
                            continue
                        if hit_id:
                            seen_ids.add(hit_id)
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
                logger.warning(f"    EDGAR error (keyword={keyword!r} form={form}): {e}")
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
        logger.warning(f"    SEDAR error: {e}")
    return filings

def scan_japan_tdnet():
    """Japan — EDINET. Requires EDINET_API_KEY (FSA started enforcing in 2024).
    Register for a free key at https://disclosure2.edinet-fsa.go.jp/weee0010.aspx"""
    filings = []
    edinet_key = os.getenv("EDINET_API_KEY", "")
    if not edinet_key:
        logger.debug("    EDINET skipped: EDINET_API_KEY not set")
        return filings
    try:
        today = datetime.now().strftime('%Y-%m-%d')
        # FSA requires Subscription-Key header AND key in query for v2
        url = f"https://disclosure.edinet-fsa.go.jp/api/v2/documents.json?date={today}&type=2&Subscription-Key={edinet_key}"
        resp = requests.get(url, headers={**HEADERS, 'Subscription-Key': edinet_key}, timeout=30)
        if resp.status_code == 401:
            logger.warning("    EDINET 401: subscription key invalid or expired")
            return filings
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
        logger.warning(f"    EDINET error: {e}")
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
        logger.warning(f"    DART error: {e}")
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
        logger.warning(f"    AMF error: {e}")
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
        logger.warning(f"    RNS error: {e}")
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
        logger.warning(f"    BaFin error: {e}")
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
        logger.warning(f"    HKEX error: {e}")
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
        logger.warning(f"    ASX error: {e}")
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
        logger.warning(f"    CVM error: {e}")
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
        logger.warning(f"    BSE error: {e}")
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
        logger.warning(f"    SGX error: {e}")
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
        logger.warning(f"    TASE error: {e}")
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
        logger.warning(f"    Oslo error: {e}")
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
        logger.warning(f"    FI Sweden error: {e}")
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
        logger.warning(f"    KAP error: {e}")
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
        logger.warning(f"    El Salvador error: {e}")
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

# ═══════════════════════════════════════════════════════════
# ACTIVE ADAPTERS — verified to produce output (probe_feeds.py 2026-05)
# ═══════════════════════════════════════════════════════════
#
# RETIRED ADAPTERS (functions kept above for future revival when sites change):
#   - scan_canada_sedar:   SEDAR+ now serves Radware captcha to all bot traffic
#   - scan_france_amf:     RSS endpoints retired (404 → "page no longer exists")
#   - scan_uk_rns:         LSE migrated to Angular SPA; Investegate RSS redirects
#   - scan_germany_bafin:  Bundesanzeiger search returns error redirect; no public RSS
#   - scan_hk_hkex:        XHTML SPA, 0 items in static HTML
#   - scan_australia_asx:  /asx-announcements.xml 404; today-anns is HTML SPA
#   - scan_brazil_cvm:     ASPX form requires viewstate POST; no public feed
#   - scan_india_sebi:     BSE 403 anti-bot on /xml-data/* and /data/xml/*
#   - scan_singapore_sgx:  api.sgx.com 403; /wcm/.../rss returns SPA HTML
#   - scan_israel_tase:    Maya RSS endpoint returns 404
#   - scan_norway_oslo:    Newsweb is a 537-byte SPA; api3.oslo 404
#   - scan_sweden_fi:      /sv/rss/marknadsinformation 404
#   - scan_turkey_kap:     /en/rss/general and /tr/rss both 404
#
# To revive any of the above: investigate whether the site now offers a JSON
# API, an authenticated feed, or a 3rd-party aggregator with stable access.
# Mechanism 2 (Google News in 15 langs) and Mechanism 3 (crypto news wires)
# already provide best-effort international coverage for retired sources.
REGULATORY_ADAPTERS = [
    ('USA-FTS', scan_usa_edgar),
    ('USA-Atom', scan_usa_edgar_atom),
    ('Japan-EDINET', scan_japan_tdnet),       # conditional on EDINET_API_KEY
    ('South Korea-DART', scan_korea_dart),    # conditional on DART_API_KEY
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
                _route_to_reconciler(filing)
                processed.add(acc)
                new_count += 1
                if filing.get('company_name') and filing.get('event_type') != 'holding':
                    _send_alert(filing.get('source', country), filing['company_name'], filing.get('event_type', 'filing'), filing.get('btc_amount', 0), filing.get('filing_url', ''))
                    total_alerts += 1
            source_stats[country] = new_count
            total_new += new_count
        except Exception as e:
            logger.warning(f"  ⚠️ {country} adapter FAILED: {e}")
            capture_exception(e, context={
                "where": "global_filing_scanner.scan_all_filings",
                "adapter": country,
                "adapter_fn": adapter.__name__,
            })
            source_stats[country] = -1  # Mark as failed, not just empty

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
            _route_to_reconciler(filing)
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
            _route_to_reconciler(filing)
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
    # Log failed and empty adapters so issues are visible
    failed = [src for src, count in source_stats.items() if count == -1]
    empty = [src for src, count in source_stats.items() if count == 0 and src not in ('Global News (15 langs)', 'Crypto News Wires')]
    if failed:
        logger.warning(f"  ❌ FAILED adapters ({len(failed)}): {', '.join(failed)}")
    if empty:
        logger.info(f"  ⓘ Empty adapters ({len(empty)}): {', '.join(empty)}")

    return {'new_filings': total_new, 'alerts': total_alerts, 'sources': source_stats}


def scan_intl_filings(days_back=1):
    """Fast-cron variant: runs only non-USA regulatory adapters.

    Skips USA adapters (edgar_realtime.py handles those via FTS) and skips
    the heavier Google News + crypto-wire mechanisms that scan_all_filings
    includes — those stay on the 3x/day cycle. Used by fast_edgar.py to
    keep international file-to-alert latency at sub-60s parity with US.

    Returns {'new_filings': int, 'alerts': int, 'sources': {country: count}}.
    """
    processed = _get_processed()
    source_stats = {}
    total_new = 0
    total_alerts = 0

    for country, adapter in REGULATORY_ADAPTERS:
        if country.startswith('USA'):
            continue
        try:
            filings = adapter(days_back) if 'days_back' in adapter.__code__.co_varnames else adapter()
            new_count = 0
            for filing in filings:
                acc = filing.get('accession_number', '')
                if acc in processed:
                    continue
                filing['processed_at'] = datetime.now().isoformat()
                filing['btc_amount'] = filing.get('btc_amount', 0)
                filing['usd_amount'] = filing.get('usd_amount', 0)
                _store_filing(filing)
                _route_to_reconciler(filing)
                processed.add(acc)
                new_count += 1
                if filing.get('company_name') and filing.get('event_type') != 'holding':
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
            logger.warning(f"  ⚠️ {country} adapter FAILED: {e}")
            capture_exception(e, context={
                "where": "global_filing_scanner.scan_intl_filings",
                "adapter": country,
                "adapter_fn": adapter.__name__,
            })
            source_stats[country] = -1

    return {'new_filings': total_new, 'alerts': total_alerts, 'sources': source_stats}


if __name__ == "__main__":
    logger.info("Global Scanner v2 — manual run (last 3 days)...")
    result = scan_all_filings(days_back=3)
    print(f"\nTotal: {result['new_filings']} new, {result['alerts']} alerts")
    print(f"Sources: {json.dumps(result['sources'], indent=2)}")
