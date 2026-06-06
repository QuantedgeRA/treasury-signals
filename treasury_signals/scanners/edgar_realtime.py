"""
edgar_realtime.py — SEC EDGAR Real-Time 8-K Filing Monitor
------------------------------------------------------------
Monitors SEC EDGAR for new 8-K filings mentioning Bitcoin.
Now routes all purchase detections through purchase_reconciler.py
for deduplication and source hierarchy management.

Primary source: https://efts.sec.gov/LATEST/search-index
No API key required. Rate limit: 10 req/sec.
"""

import os
import re
import json
import time
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
from supabase import create_client
from treasury_signals.logger import get_logger
from treasury_signals.pipelines.purchase_reconciler import reconcile_and_save, reconcile_sale
from treasury_signals.observability import capture_exception
from treasury_signals.freshness_tracker import freshness

logger = get_logger(__name__)
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_PAID_CHANNEL_ID = os.getenv("TELEGRAM_PAID_CHANNEL_ID")

EDGAR_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
EDGAR_FILING_URL = "https://www.sec.gov/Archives/edgar/data"

# Forms we full-text search, in priority order:
#   8-K, 8-K/A   — ad-hoc material event filings (the real-time focus)
#   10-Q          — quarterly report
#   10-K, 10-K/A  — annual report (treasury policy language + risk factors)
#
# CRITICAL: EFTS mis-parses any `forms` value that contains an amendment form
# with a slash ("8-K/A", "10-K/A"). Passing such a value — alone OR inside a
# comma list — silently collapses the *entire* result set to ~1 hit while still
# returning HTTP 200, so the failure is invisible. This bricked the real-time
# scanner for ~2 weeks (only 4 filings in DB, 2wk stale). Verified 2026-06-01:
#   forms=8-K,10-Q,10-K            -> 345 hits   (comma list is fine)
#   forms=8-K,8-K/A,10-Q,10-K,...  ->   1 hit    (any /A form poisons it)
#   forms=8-K/A                    ->   1 hit    (even alone; %2F-encoding too)
# Fix: issue ONE request per form (each single-form query is the documented
# happy path) and merge the hits, deduping by EFTS `_id`.
EDGAR_FORMS = ['8-K', '8-K/A', '10-Q', '10-K', '10-K/A']
EDGAR_REQUEST_THROTTLE_SEC = 0.15  # ~7 req/sec, comfortably under EDGAR's 10/sec cap

SEARCH_TERMS = [
    '"bitcoin"',
    '"btc"',
    '"digital asset" AND "treasury"',
    '"bitcoin treasury"',
    '"cryptocurrency" AND "purchase"',
]

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

# btc_amount is the TRANSACTION delta (bought/sold) we alert on — phases.py
# renders it verbatim as "acquired {btc_amount} BTC" and routes it to the
# reconciler. It must therefore be the period transaction, NEVER the running
# holdings total. Real filings verified 2026-06-02 phrase purchases as e.g.
# MSTR "used these proceeds to purchase 24,869 bitcoin", ABTC "added more than
# 1,600 Bitcoin" / "Acquired ~803 Bitcoin" — base-form verbs, filler words and
# a "~" prefix the old patterns missed, so extraction fell through to the
# holdings total (MSTR 843,738) and overstated every alert by ~30x.
#
# NOTE: extractors lowercase the text first, so all literals here are lowercase
# (the old code carried an uppercase "BTC" alternative that could never match).
#
# KNOWN LIMITATION (US-format assumption): _NUM treats ',' as the thousands
# separator and '.' as the decimal point, which is correct for SEC filings (US
# format) — this scanner's domain. It does NOT handle European notation, where
# "12.500" means 12,500 and "1.234,56" means 1234.56. A naive fix is unsafe:
# bare "12.500" is genuinely ambiguous (EU 12,500 vs US 12.5) and guessing wrong
# is a 1000x error either way, so it's left as US. International filings that use
# EU notation should be parsed with locale context in their own adapters
# (global_filing_scanner / purchase_tracker), NOT by widening this US regex.
_NUM = r'(\d{1,3}(?:,\d{3})*(?:\.\d+)?)'
# Filler tokens that commonly sit between the verb and the number.
_FILL = (r'(?:approximately\s+|~\s*|about\s+|over\s+|more\s+than\s+|nearly\s+|'
         r'an?\s+additional\s+|an?\s+aggregate\s+of\s+|a\s+total\s+of\s+|up\s+to\s+)*')
BTC_TXN_PATTERNS = [
    # verb (base OR past tense, incl. "to purchase") -> filler -> number -> btc.
    # _FILL only admits specific filler tokens, so the number must sit right
    # after the verb — this is what keeps "BTC Gain of 4,391 bitcoin" and
    # "starting amount of 100,000 bitcoin" (no acquisition verb) from matching.
    rf'\b(?:to\s+)?(?:acquir(?:e|ed)|purchas(?:e|ed)|bought|buy|add(?:ed)?|'
    rf'sold|sell|dispos(?:e|ed)\s+of|divest(?:ed)?)\s+{_FILL}{_NUM}\s*(?:btc|bitcoins?)\b',
    # number -> btc -> trailing/passive verb ("24,869 bitcoin were purchased").
    rf'{_NUM}\s*(?:btc|bitcoins?)\s+(?:were\s+|was\s+)?(?:acquired|purchased|bought|added|sold)\b',
]
# Holdings/total patterns — surfaced in logs for ops visibility ONLY. Never fed
# to btc_amount (see _extract_btc_holdings).
BTC_HOLDINGS_PATTERNS = [
    rf'(?:holds?|holding|total of|aggregate of|now owns?|reserve of)\s+(?:approximately\s+|~\s*)?{_NUM}\s*(?:btc|bitcoins?)',
    rf'(?:approximately\s+|~\s*)?{_NUM}\s*(?:btc|bitcoins?)',
]

# USD patterns capture (number, unit) so we can scale PER MATCH. The old code
# scaled by whether 'billion'/'B' appeared ANYWHERE in the document — and a
# bare capital 'B' is in almost every filing — so e.g. "$871 million" was
# inflated to $871 *billion*. Unit is now read from the adjacent token only.
USD_PATTERNS = [
    rf'\$\s*{_NUM}\s*(million|billion|bn|mm|m|b)\b',
    rf'{_NUM}\s*(million|billion)\s*(?:dollars|usd|\$)',
]
_USD_SCALE = {'billion': 1_000_000_000, 'bn': 1_000_000_000, 'b': 1_000_000_000,
              'million': 1_000_000, 'mm': 1_000_000, 'm': 1_000_000}

HEADERS = {
    'User-Agent': 'TreasurySignalIntelligence admin@quantedgeriskadvisory.com',
    'Accept': 'application/json',
}


def _resolve_ticker(edgar_name, edgar_cik=""):
    """
    Resolve an EDGAR entity name to the actual ticker in our treasury_companies table.
    EDGAR returns names like 'MICROSTRATEGY INC' but we need 'MSTR'.
    
    Strategy:
      1. Exact name match (case-insensitive)
      2. Partial name match (EDGAR name contains or is contained in our name)
      3. CIK-based lookup if available
      4. Fallback: return the EDGAR name as-is
    """
    if not edgar_name:
        return edgar_name, edgar_name
    
    try:
        result = supabase.table("treasury_companies").select("company, ticker").gt("btc_holdings", 0).execute()
        if not result.data:
            return edgar_name, ""
        
        edgar_clean = edgar_name.upper().strip()
        # Remove common suffixes for matching
        for suffix in [' INC', ' INC.', ' CORP', ' CORP.', ' LTD', ' LTD.', ' LLC', ' PLC', ' CO', ' CO.', ' GROUP', ' HOLDINGS', ' GLOBAL', ',']:
            edgar_clean = edgar_clean.replace(suffix, '')
        edgar_clean = edgar_clean.strip()
        
        best_match = None
        best_score = 0
        
        for row in result.data:
            db_name = (row.get('company', '') or '').upper().strip()
            db_ticker = row.get('ticker', '') or ''
            
            db_clean = db_name
            for suffix in [' INC', ' INC.', ' CORP', ' CORP.', ' LTD', ' LTD.', ' LLC', ' PLC', ' CO', ' CO.', ' GROUP', ' HOLDINGS', ' GLOBAL', ' (MICROSTRATEGY)', ',']:
                db_clean = db_clean.replace(suffix, '')
            db_clean = db_clean.strip()
            
            # Exact match after cleaning
            if edgar_clean == db_clean:
                return row['company'], db_ticker
            
            # One contains the other
            if edgar_clean in db_clean or db_clean in edgar_clean:
                score = min(len(edgar_clean), len(db_clean)) / max(len(edgar_clean), len(db_clean), 1)
                if score > best_score and score > 0.5:
                    best_score = score
                    best_match = row
            
            # First word match (e.g., "STRATEGY" matches "Strategy (MicroStrategy)")
            edgar_first = edgar_clean.split()[0] if edgar_clean.split() else ''
            db_first = db_clean.split()[0] if db_clean.split() else ''
            if edgar_first and db_first and edgar_first == db_first and len(edgar_first) >= 4:
                score = 0.7
                if score > best_score:
                    best_score = score
                    best_match = row
        
        if best_match:
            logger.debug(f"  EDGAR ticker resolved: '{edgar_name}' → '{best_match['company']}' ({best_match['ticker']})")
            return best_match['company'], best_match['ticker']
        
    except Exception as e:
        logger.debug(f"  EDGAR ticker resolution error: {e}")
    
    return edgar_name, ""


def _search_edgar(query, days_back=1):
    """
    Full-text EDGAR search for `query` across every form in EDGAR_FORMS, one
    HTTP request per form (see the EDGAR_FORMS note for why a single combined
    request can't be used). 10-Q/10-K are bigger docs but carry the treasury
    policy language + risk factors persona A's IR team wants; the excerpt
    extractor dedups identical sentences so we don't re-alert on boilerplate.

    Returns (hits, requests_made, request_errors):
      hits           — merged, deduped list of EFTS hit dicts (by `_id`)
      requests_made  — number of form requests attempted
      request_errors — how many of those failed (network/HTTP/JSON)
    The caller uses the error counts to drive the freshness alarm so a broken
    source can no longer masquerade as a quiet news day.
    """
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')

    merged = {}
    requests_made = 0
    request_errors = 0

    for form in EDGAR_FORMS:
        params = {
            'q': query,
            'dateRange': 'custom',
            'startdt': start_date,
            'enddt': end_date,
            'forms': form,  # one form per request — see EDGAR_FORMS note above
        }
        requests_made += 1
        try:
            resp = requests.get(EDGAR_SEARCH_URL, params=params, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            for hit in resp.json().get('hits', {}).get('hits', []):
                hit_id = hit.get('_id')
                if hit_id:
                    merged[hit_id] = hit
        except Exception as e:
            request_errors += 1
            # NOT debug. Swallowing this at debug level is exactly what kept the
            # last 2-week outage invisible. Warn loudly + ship to Sentry; the
            # caller escalates to Telegram if the whole scan goes dark.
            logger.warning(f"EDGAR search request failed (q={query!r} form={form}): {e}")
            capture_exception(e, context={
                "where": "edgar_realtime._search_edgar",
                "query": query, "form": form,
                "startdt": start_date, "enddt": end_date,
            })
        finally:
            time.sleep(EDGAR_REQUEST_THROTTLE_SEC)

    return list(merged.values()), requests_made, request_errors


def _fetch_filing_text(filing_url):
    try:
        time.sleep(0.5)
        resp = requests.get(filing_url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        text = re.sub(r'<[^>]+>', ' ', resp.text)
        text = re.sub(r'\s+', ' ', text)
        return text[:50000]
    except Exception as e:
        logger.debug(f"  EDGAR fetch error: {e}")
        return ""


def _parse_amounts(matches):
    out = []
    for m in matches:
        try:
            out.append(float(m.replace(',', '')))
        except (ValueError, AttributeError):
            pass
    return out


def _extract_btc_amount(text):
    """Return the TRANSACTED BTC amount (the bought/sold delta we alert on).

    Returns 0 when the filing states no transaction amount. We deliberately do
    NOT fall back to the holdings total: a holdings/earnings 8-K (e.g. RIOT
    reporting it "maintained 15,679 bitcoin") is not a purchase, and routing the
    cumulative total as the transaction amount would announce a ~15,000 BTC buy
    that never happened. Use _extract_btc_holdings() for the running total.
    """
    text_lower = text.lower()
    for pattern in BTC_TXN_PATTERNS:
        amounts = _parse_amounts(re.findall(pattern, text_lower))
        if amounts:
            return max(amounts)
    return 0


def _extract_btc_holdings(text):
    """Cumulative treasury total stated in the filing (NOT a transaction).
    Surfaced in logs for ops/extraction visibility — never the alert amount."""
    text_lower = text.lower()
    for pattern in BTC_HOLDINGS_PATTERNS:
        amounts = _parse_amounts(re.findall(pattern, text_lower))
        if amounts:
            return max(amounts)
    return 0


def _extract_usd_amount(text):
    """Largest USD figure in the filing, scaled by the unit token adjacent to
    each number (not a document-wide guess)."""
    text_lower = text.lower()
    amounts = []
    for pattern in USD_PATTERNS:
        for num, unit in re.findall(pattern, text_lower):
            try:
                amounts.append(float(num.replace(',', '')) * _USD_SCALE.get(unit, 1))
            except (ValueError, AttributeError):
                pass
    return max(amounts) if amounts else 0


def _classify_event(text):
    text_lower = text.lower()
    purchase_score = sum(1 for kw in PURCHASE_KEYWORDS if kw in text_lower)
    sale_score = sum(1 for kw in SALE_KEYWORDS if kw in text_lower)
    if purchase_score > sale_score:
        return 'purchase'
    elif sale_score > purchase_score:
        return 'sale'
    return 'holding'


def _get_processed_filings(accessions):
    """Return the subset of `accessions` already in edgar_filings.

    Bounded by the candidate list (this scan's hits), NOT the whole table —
    the old `select(accession_number)` with no filter loaded every row and
    PostgREST silently capped it at 1000, so once edgar_filings passed 1000
    (it's now ~6k) the dedup set was missing ~5k accessions and recently-seen
    filings were re-fetched / re-Claude-scored / re-routed every run. Querying
    only the candidates is exact and scales with hits, not table size.
    """
    accessions = [a for a in dict.fromkeys(accessions) if a]  # de-dupe, drop blanks
    if not accessions:
        return set()
    found = set()
    for i in range(0, len(accessions), 100):  # chunk to keep the IN() URL bounded
        chunk = accessions[i:i + 100]
        try:
            result = supabase.table("edgar_filings").select("accession_number").in_(
                "accession_number", chunk
            ).execute()
            found.update(r['accession_number'] for r in (result.data or []))
        except Exception as e:
            logger.debug(f"  EDGAR processed-filings lookup failed for a chunk: {e}")
    return found


# Columns added by migration 0023; code is forward-compatible if it isn't
# applied yet (the store retries without them rather than losing the filing).
_OPTIONAL_EDGAR_COLS = ('acceptance_datetime', 'alerted_at')


def _is_missing_column_error(exc):
    s = str(exc).lower()
    return 'column' in s and ('does not exist' in s or 'could not find' in s or 'schema cache' in s)


def _store_filing(filing_data):
    try:
        supabase.table("edgar_filings").upsert(filing_data, on_conflict="accession_number").execute()
        return
    except Exception as e:
        # Forward-compat: if migration 0023 (acceptance_datetime/alerted_at)
        # hasn't been applied yet, drop those keys and retry so the core write
        # still lands. Any other error is real.
        if _is_missing_column_error(e) and any(k in filing_data for k in _OPTIONAL_EDGAR_COLS):
            trimmed = {k: v for k, v in filing_data.items() if k not in _OPTIONAL_EDGAR_COLS}
            try:
                supabase.table("edgar_filings").upsert(trimmed, on_conflict="accession_number").execute()
                logger.warning("  EDGAR store: acceptance_datetime/alerted_at columns absent — stored without them (apply migration 0023)")
                return
            except Exception as e2:
                e = e2
        logger.warning(f"  EDGAR store error: {e} (accession={filing_data.get('accession_number','')})")
        capture_exception(e, context={
            "where": "edgar_realtime._store_filing",
            "accession": filing_data.get("accession_number", ""),
            "company": filing_data.get("company_name", "")[:80],
            "event_type": filing_data.get("event_type", ""),
        })


def _claim_alert(accession, now_iso):
    """Atomically claim the right to alert on a filing.

    Returns True ONLY for the process that transitions alerted_at NULL->now via
    a conditional UPDATE. Postgres serializes the row update, so when a worker
    full-scan and a fast_edgar cron both reach the same accession, exactly one
    sees a matching row (alerted_at IS NULL) and alerts; the other gets 0 rows
    and stays quiet. Fail-OPEN: if the claim query errors (e.g. the alerted_at
    column is absent pre-migration-0023), allow the alert rather than silently
    dropping a real signal — duplicate-suppression must never cause a miss.
    """
    try:
        res = (
            supabase.table("edgar_filings")
            .update({"alerted_at": now_iso})
            .eq("accession_number", accession)
            .is_("alerted_at", "null")
            .execute()
        )
        return bool(res.data)
    except Exception as e:
        logger.debug(f"  EDGAR alert-claim error for {accession} (alerting anyway): {e}")
        return True


_acceptance_cache = {}


def _fetch_acceptance_datetime(cik, accession):
    """Return the SEC acceptanceDateTime (ISO-8601) for a filing, or None.

    EFTS hits carry only file_date (a calendar day). The precise acceptance
    timestamp — needed to measure true file->alert latency — lives in the
    data.sec.gov submissions API, whose filings.recent arrays pair each
    accessionNumber with its acceptanceDateTime. Cached per CIK per process.
    """
    if not cik or not accession:
        return None
    try:
        cik_int = int(cik)
    except (ValueError, TypeError):
        return None

    if cik_int not in _acceptance_cache:
        mapping = {}
        try:
            url = f"https://data.sec.gov/submissions/CIK{cik_int:010d}.json"
            resp = requests.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            recent = resp.json().get('filings', {}).get('recent', {})
            accs = recent.get('accessionNumber', []) or []
            accepts = recent.get('acceptanceDateTime', []) or []
            mapping = dict(zip(accs, accepts))
        except Exception as e:
            logger.debug(f"  EDGAR acceptance fetch error (cik={cik}): {e}")
        finally:
            time.sleep(0.2)
        _acceptance_cache[cik_int] = mapping

    return _acceptance_cache[cik_int].get(accession)


def _send_alert(company, ticker, event_type, btc_amount, usd_amount, filing_url, direction=None):
    """Send the SEC-filing Telegram alert.

    The optional `direction` arg activates the filing-impact predictor:
    when a direction (pure_buy / raise_then_buy / convertible / sale /
    unclear) is supplied, we look up historical reaction stats from
    backtest_reactions and embed an "expected reaction" block in the
    alert. Customers get a trade thesis alongside the raw event.

    The predictor is fail-open: if stats lookup hiccups or sample size
    is too small, the alert still fires without the block.
    """
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

    # Direction-aware impact predictor block. Surface ONLY for purchase
    # events with a direction classification — sale events have their own
    # reaction pattern but the n_events is tiny in current data (1) so
    # the block would be misleading.
    if direction and event_type == 'purchase':
        try:
            from treasury_signals.pipelines.filing_impact_predictor import (
                get_historical_reactions, format_impact_context_telegram,
            )
            stats = get_historical_reactions(direction, ticker=ticker)
            if stats:
                msg += format_impact_context_telegram(stats, ticker or company)
        except Exception as e:
            logger.debug(f"  EDGAR impact predictor: {e}")

    msg += f"\n📄 [View Filing]({filing_url})\n"
    msg += f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}"
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={'chat_id': TELEGRAM_PAID_CHANNEL_ID, 'text': msg, 'parse_mode': 'Markdown', 'disable_web_page_preview': True},
            timeout=10,
        )
        logger.info(f"  EDGAR alert sent: {company} {event_type} {btc_amount} BTC dir={direction}")
    except Exception as e:
        logger.debug(f"  EDGAR alert error: {e}")


def check_edgar_filings(days_back=1):
    """
    Main function: Search EDGAR for new Bitcoin-related 8-K filings.
    Purchase-type filings are routed through the reconciler for
    deduplication and source hierarchy management.
    """
    logger.info("EDGAR realtime: checking for new filings...")

    new_filings = 0
    alerts_sent = 0
    total_requests = 0
    total_request_errors = 0
    total_hits_scanned = 0

    for query in SEARCH_TERMS:
        hits, requests_made, request_errors = _search_edgar(query, days_back)
        total_requests += requests_made
        total_request_errors += request_errors
        total_hits_scanned += len(hits)
        if not hits:
            continue

        # Dedup against ONLY this term's candidate accessions (bounded query —
        # see _get_processed_filings). Cross-term duplicates are still caught:
        # each filing is stored immediately on processing, so it shows up in the
        # next term's lookup; within a term, processed.add() guards repeats.
        candidates = [
            (h.get('_source', {}).get('adsh', '') or h.get('_id', '').split(':')[0])
            for h in hits
        ]
        processed = _get_processed_filings(candidates)

        for hit in hits:
            source = hit.get('_source', {})
            # EDGAR FTS hit shape: _id = "accession:filename", _source.adsh = accession,
            # _source.ciks = [cik], _source.form = "8-K", _source.display_names = ["NAME (TICKER) (CIK ...)"]
            accession = source.get('adsh', '') or hit.get('_id', '').split(':')[0]
            if not accession or accession in processed:
                continue

            display_names = source.get('display_names', []) or []
            display = display_names[0] if display_names else ''
            company_name = display.split('(')[0].strip() if display else ''

            ticker_match = re.search(r'\(([A-Z][A-Z0-9.\-]{0,5})\)', display)
            ticker_cik = ticker_match.group(1) if ticker_match else ''

            ciks = source.get('ciks', []) or []
            cik = ciks[0] if ciks else ''
            filing_date = source.get('file_date', '')
            form_type = source.get('form', '8-K')

            # Reconstruct the primary document URL from CIK + accession + filename
            hit_id = hit.get('_id', '')
            filename = hit_id.split(':', 1)[1] if ':' in hit_id else ''
            if cik and accession and filename:
                accession_clean = accession.replace('-', '')
                try:
                    cik_int = int(cik)
                    primary_doc_url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_clean}/{filename}"
                    filing_url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_clean}/"
                except ValueError:
                    primary_doc_url = ''
                    filing_url = ''
            else:
                primary_doc_url = ''
                filing_url = ''

            text = _fetch_filing_text(primary_doc_url) if primary_doc_url else ''
            if not text:
                continue

            text_lower = text.lower()
            if not any(term in text_lower for term in ['bitcoin', 'btc', 'digital asset treasury', 'cryptocurrency reserve']):
                continue

            btc_amount = _extract_btc_amount(text)
            btc_holdings = _extract_btc_holdings(text)
            usd_amount = _extract_usd_amount(text)
            event_type = _classify_event(text)

            # Direction classifier — tags the filing as pure_buy / raise_then_buy /
            # convertible / sale / unclear so traders know which way the stock
            # is likely to move. See pipelines/direction_classifier.py for the
            # pattern library. Defensive: never crash the EDGAR scan on a
            # classifier hiccup, since direction is enrichment, not core data.
            direction = None
            direction_confidence = None
            try:
                from treasury_signals.pipelines.direction_classifier import classify_direction
                dir_result = classify_direction(text)
                direction = dir_result.direction
                direction_confidence = dir_result.confidence
            except Exception as e:
                logger.debug(f"  Direction classifier error: {e}")

            # Store in edgar_filings table
            # Acceptance timestamp (when the SEC actually accepted the filing) —
            # lets us measure true file->alert latency instead of guessing.
            now = datetime.now()
            acceptance_iso = _fetch_acceptance_datetime(cik, accession)
            latency_note = ""
            if acceptance_iso:
                try:
                    acc_dt = datetime.fromisoformat(acceptance_iso.replace('Z', '+00:00')).replace(tzinfo=None)
                    latency_s = (datetime.utcnow() - acc_dt).total_seconds()
                    latency_note = f" | file->detect latency: {latency_s/60:.1f} min"
                except Exception:
                    pass

            filing_data = {
                'accession_number': accession,
                'company_name': company_name[:200],
                'ticker_cik': ticker_cik[:50],
                'filing_date': filing_date or now.strftime('%Y-%m-%d'),
                'form_type': form_type,
                'event_type': event_type,
                'btc_amount': btc_amount,
                'usd_amount': usd_amount,
                'filing_url': filing_url[:500],
                'processed_at': now.isoformat(),
                'direction': direction,
                'direction_confidence': direction_confidence,
                # MUST start with "SEC EDGAR" — the excerpt extractor (the moat
                # pipeline) filters edgar_filings to source LIKE 'SEC EDGAR%' to
                # skip the Google-News rows. Without this, realtime filings would
                # store source=NULL and be invisible to the moat.
                'source': 'SEC EDGAR 8-K (real-time)',
                'acceptance_datetime': acceptance_iso,
                # alerted_at is intentionally NOT set here — it's the atomic
                # alert-claim flag (set only by the process that wins the right
                # to alert, just before _send_alert). See _claim_alert().
            }
            _store_filing(filing_data)
            processed.add(accession)
            new_filings += 1

            # Route purchase-type filings through the reconciler
            if event_type in ('purchase', 'acquisition') and btc_amount > 0:
                # Resolve EDGAR entity name to our database ticker
                resolved_name, resolved_ticker = _resolve_ticker(company_name, ticker_cik)
                
                purchase = {
                    "company": resolved_name or company_name,
                    "ticker": resolved_ticker or ticker_cik,
                    "btc_amount": btc_amount,
                    "usd_amount": usd_amount,
                    "price_per_btc": round(usd_amount / btc_amount) if btc_amount > 0 and usd_amount > 0 else 0,
                    "filing_date": filing_data['filing_date'],
                    "filing_url": filing_url,
                    "source": f"SEC EDGAR 8-K (real-time)",
                    "notes": f"Accession: {accession}. EDGAR entity: {company_name}",
                    "direction": direction,
                    "direction_confidence": direction_confidence,
                }
                result = reconcile_and_save(purchase, source_type="edgar", is_new_entrant=False)
                logger.info(f"  EDGAR → Reconciler: {company_name} — {result['action']} (direction: {direction})")

            # Route sale-type filings through the sale reconciler
            elif event_type == 'sale' and btc_amount > 0:
                resolved_name, resolved_ticker = _resolve_ticker(company_name, ticker_cik)
                
                sale = {
                    "company": resolved_name or company_name,
                    "ticker": resolved_ticker or ticker_cik,
                    "btc_amount": btc_amount,
                    "usd_amount": usd_amount,
                    "price_per_btc": round(usd_amount / btc_amount) if btc_amount > 0 and usd_amount > 0 else 0,
                    "filing_date": filing_data['filing_date'],
                    "filing_url": filing_url,
                    "source": f"SEC EDGAR 8-K (real-time)",
                    "notes": f"Sale detected. Accession: {accession}. EDGAR entity: {company_name}",
                }
                result = reconcile_sale(sale, source_type="edgar")
                logger.info(f"  EDGAR → Sale Reconciler: {company_name} — {result['action']}")

            # Send Telegram alert for purchases and sales. Atomic alert-claim:
            # only the process that flips alerted_at NULL->now sends it, so a
            # worker full-scan (6/12/18 UTC) and a fast_edgar */2 cron hitting
            # the same accession in the same window can't BOTH fire. Direction
            # is passed through for the filing-impact predictor.
            if event_type in ('purchase', 'sale') and (btc_amount > 0 or usd_amount > 0):
                if _claim_alert(accession, now.isoformat()):
                    _send_alert(
                        company_name, ticker_cik, event_type, btc_amount, usd_amount, filing_url,
                        direction=direction,
                    )
                    alerts_sent += 1

            holdings_note = f" (holds ~{btc_holdings:,.0f})" if btc_holdings else ""
            logger.info(f"  EDGAR: {company_name} — {event_type} — txn {btc_amount:,.0f} BTC{holdings_note} — {filing_date}{latency_note}")

        time.sleep(1)

    logger.info(f"EDGAR realtime: {new_filings} new filings, {alerts_sent} alerts sent")

    # Source-health report (#8). The old code swallowed request errors at debug
    # level and returned [], so a broken EFTS query looked identical to a quiet
    # news day — which is how the /A-forms bug stayed invisible for ~2 weeks.
    # Now we report scan health to the freshness tracker (source_id "sec_edgar",
    # which was registered but never reported to). A total wipeout — every form
    # request across every search term failed — is a real outage and records a
    # failure; the tracker escalates to admin Telegram after 3 consecutive ones,
    # so a single quiet/weekend scan never false-alarms. Any successful request
    # (even one returning zero hits) means EDGAR is reachable and answering, so
    # the source is healthy and we reset the failure streak.
    if total_requests > 0 and total_request_errors >= total_requests:
        freshness.record_failure(
            "sec_edgar",
            error=f"all {total_request_errors}/{total_requests} EFTS requests failed over last {days_back}d",
        )
    else:
        freshness.record_success(
            "sec_edgar",
            detail=f"{new_filings} new filing(s), {total_hits_scanned} hits scanned, "
                   f"{total_request_errors}/{total_requests} req errors",
        )

    return {
        'new_filings': new_filings,
        'alerts_sent': alerts_sent,
        'requests': total_requests,
        'request_errors': total_request_errors,
        'hits_scanned': total_hits_scanned,
    }


if __name__ == "__main__":
    logger.info("EDGAR realtime — manual run (last 3 days)...")
    result = check_edgar_filings(days_back=3)
    print(f"New filings: {result['new_filings']}, Alerts: {result['alerts_sent']}")
